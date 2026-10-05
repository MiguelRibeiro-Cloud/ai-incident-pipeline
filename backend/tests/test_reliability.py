from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from google.genai.errors import ClientError, ServerError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.execution import ExecutionEventType, JobExecutionEvent, ServiceAnalysisRecord
from app.schemas.analysis import IncidentReport, ServiceAnalysis
from app.services.llm_errors import (
    PermanentLLMError,
    TransientLLMError,
    classify_provider_exception,
)
from app.tasks.process_incident import (
    analyze_service,
    normalize_incident_payload,
    synthesize_incident_report,
)

INCIDENT = {
    "title": "Checkout degradation",
    "environment": "test",
    "events": [
        {
            "timestamp": "2026-10-05T08:02:10Z",
            "source": "application",
            "service": "checkout-api",
            "severity": "ERROR",
            "message": "HTTP 503 rate exceeded threshold",
        }
    ],
}
ANALYSIS = {
    "service": "checkout-api",
    "summary": "Elevated errors were observed.",
    "probable_cause": "The evidence suggests service degradation.",
    "confidence": 0.8,
    "evidence": [
        {
            "timestamp": "2026-10-05T08:02:10Z",
            "observation": "HTTP 503 rate exceeded threshold",
        }
    ],
    "recommended_checks": ["Inspect checkout health"],
}
REPORT = {
    "executive_summary": "Checkout errors were observed.",
    "probable_root_cause": "The evidence points to checkout degradation.",
    "confidence": 0.8,
    "affected_services": ["checkout-api"],
    "impact": "Checkout requests failed.",
    "timeline_summary": "The supplied event records elevated errors.",
    "supporting_evidence": ["HTTP 503 rate exceeded threshold"],
    "recommended_actions": ["Inspect checkout health"],
}


@contextmanager
def _same_session(session: Session) -> Generator[Session, None, None]:
    yield session


def _job(session: Session, *, incident: dict | None = None) -> AnalysisJob:
    payload = incident or INCIDENT
    job = AnalysisJob(
        status=JobStatus.PROCESSING,
        progress=40,
        incident=payload,
        normalized_incident=normalize_incident_payload(payload),
        deterministic_summary={"services": ["checkout-api"]},
    )
    session.add(job)
    session.commit()
    return job


def _run_service(job: AnalysisJob, retries: int = 0):
    analyze_service.push_request(id="service-task", retries=retries, delivery_info={})
    try:
        return analyze_service.run(str(job.id), "checkout-api")
    finally:
        analyze_service.pop_request()


def _run_synthesis(job: AnalysisJob, retries: int = 0):
    synthesize_incident_report.push_request(id="synthesis-task", retries=retries, delivery_info={})
    try:
        return synthesize_incident_report.run([ANALYSIS], str(job.id))
    finally:
        synthesize_incident_report.pop_request()


def test_provider_error_classification_is_selective() -> None:
    assert isinstance(classify_provider_exception(ServerError(503, {})), TransientLLMError)
    assert isinstance(classify_provider_exception(ClientError(429, {})), TransientLLMError)
    assert isinstance(classify_provider_exception(TimeoutError()), TransientLLMError)
    assert isinstance(classify_provider_exception(ClientError(400, {})), PermanentLLMError)
    programming_error = TypeError("bug")
    assert classify_provider_exception(programming_error) is programming_error


def test_ai_tasks_use_late_ack_and_fair_worker_prefetch() -> None:
    assert analyze_service.acks_late is True
    assert analyze_service.reject_on_worker_lost is True
    assert analyze_service.max_retries == 3
    assert synthesize_incident_report.acks_late is True
    assert synthesize_incident_report.reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_transient_failure_schedules_retry_without_failing_job(db_session: Session) -> None:
    job = _job(db_session)
    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_session(db_session),
        ),
        patch(
            "app.tasks.process_incident.generate_service_analysis",
            side_effect=TransientLLMError("temporary"),
        ),
        patch("app.tasks.process_incident.retry_delay_seconds", return_value=1.25),
        patch.object(analyze_service, "retry", side_effect=Retry()),
        pytest.raises(Retry),
    ):
        _run_service(job)

    db_session.refresh(job)
    assert job.status == JobStatus.PROCESSING
    retry = db_session.scalar(
        select(JobExecutionEvent).where(
            JobExecutionEvent.job_id == job.id,
            JobExecutionEvent.event_type == ExecutionEventType.RETRY_SCHEDULED,
        )
    )
    assert retry is not None
    assert retry.attempt == 1
    assert retry.metadata_json == {"countdown_seconds": 1.25, "next_attempt": 2}


def test_nonretryable_and_malformed_output_fail_immediately(db_session: Session) -> None:
    for failure in (
        PermanentLLMError("HTTP 400"),
        ValidationError.from_exception_data("ServiceAnalysis", []),
    ):
        job = _job(db_session)
        with (
            patch(
                "app.tasks.process_incident.SessionLocal",
                side_effect=lambda: _same_session(db_session),
            ),
            patch("app.tasks.process_incident.generate_service_analysis", side_effect=failure),
            pytest.raises(type(failure)),
        ):
            _run_service(job)
        db_session.refresh(job)
        assert job.status == JobStatus.FAILED
        assert not db_session.scalar(
            select(JobExecutionEvent.id).where(
                JobExecutionEvent.job_id == job.id,
                JobExecutionEvent.event_type == ExecutionEventType.RETRY_SCHEDULED,
            )
        )


def test_exhausted_transient_retries_mark_job_failed(db_session: Session) -> None:
    job = _job(db_session)
    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_session(db_session),
        ),
        patch(
            "app.tasks.process_incident.generate_service_analysis",
            side_effect=TransientLLMError("still unavailable"),
        ),
        pytest.raises(TransientLLMError),
    ):
        _run_service(job, retries=3)
    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "still unavailable" in job.error


def test_duplicate_success_reuses_one_persistent_service_result(db_session: Session) -> None:
    job = _job(db_session)
    generated = ServiceAnalysis.model_validate(ANALYSIS)
    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_session(db_session),
        ),
        patch(
            "app.tasks.process_incident.generate_service_analysis", return_value=generated
        ) as generate,
    ):
        assert _run_service(job) == ANALYSIS
        assert _run_service(job) == ANALYSIS
    assert generate.call_count == 1
    assert db_session.scalar(select(func.count(ServiceAnalysisRecord.id))) == 1


def test_service_result_database_constraint_rejects_duplicate(db_session: Session) -> None:
    job = _job(db_session)
    db_session.add_all(
        [
            ServiceAnalysisRecord(job_id=job.id, service="checkout-api", analysis=ANALYSIS),
            ServiceAnalysisRecord(job_id=job.id, service="checkout-api", analysis=ANALYSIS),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_chaos_fails_two_attempts_before_any_gemini_request(db_session: Session) -> None:
    incident = {
        **INCIDENT,
        "chaos": {"enabled": True, "fail_service": "checkout-api", "fail_attempts": 2},
    }
    job = _job(db_session, incident=incident)
    generated = ServiceAnalysis.model_validate(ANALYSIS)
    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_session(db_session),
        ),
        patch("app.tasks.process_incident.settings.enable_chaos_demo", True),
        patch("app.tasks.process_incident.retry_delay_seconds", return_value=1),
        patch.object(analyze_service, "retry", side_effect=Retry()),
        patch(
            "app.tasks.process_incident.generate_service_analysis", return_value=generated
        ) as generate,
    ):
        with pytest.raises(Retry):
            _run_service(job, retries=0)
        with pytest.raises(Retry):
            _run_service(job, retries=1)
        assert generate.call_count == 0
        assert _run_service(job, retries=2) == ANALYSIS
    assert generate.call_count == 1
    chaos_count = db_session.scalar(
        select(func.count(JobExecutionEvent.id)).where(
            JobExecutionEvent.job_id == job.id,
            JobExecutionEvent.event_type == ExecutionEventType.CHAOS_FAILURE_INJECTED,
        )
    )
    assert chaos_count == 2


def test_retry_recovery_then_synthesis_completes_once(db_session: Session) -> None:
    job = _job(db_session)
    generated = ServiceAnalysis.model_validate(ANALYSIS)
    report = IncidentReport.model_validate(REPORT)
    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_session(db_session),
        ),
        patch("app.tasks.process_incident.retry_delay_seconds", return_value=1),
        patch.object(analyze_service, "retry", side_effect=Retry()),
        patch(
            "app.tasks.process_incident.generate_service_analysis",
            side_effect=[TransientLLMError("temporary"), generated],
        ),
        patch(
            "app.tasks.process_incident.generate_incident_report", return_value=report
        ) as synthesize,
    ):
        with pytest.raises(Retry):
            _run_service(job, retries=0)
        assert synthesize.call_count == 0
        assert _run_service(job, retries=1) == ANALYSIS
        assert _run_synthesis(job) == str(job.id)
        assert _run_synthesis(job) == str(job.id)

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100
    assert synthesize.call_count == 1
    assert (
        db_session.scalar(
            select(func.count(JobExecutionEvent.id)).where(
                JobExecutionEvent.job_id == job.id,
                JobExecutionEvent.event_type == ExecutionEventType.JOB_COMPLETED,
            )
        )
        == 1
    )


def test_event_api_is_chronological(client, db_session: Session) -> None:
    job = _job(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            JobExecutionEvent(
                job_id=job.id,
                created_at=now + timedelta(seconds=1),
                event_type=ExecutionEventType.TASK_SUCCEEDED,
                stage="analyze_service",
                message="second",
            ),
            JobExecutionEvent(
                job_id=job.id,
                created_at=now,
                event_type=ExecutionEventType.TASK_STARTED,
                stage="analyze_service",
                message="first",
            ),
        ]
    )
    db_session.commit()
    response = client.get(f"/api/v1/jobs/{job.id}/events")
    assert response.status_code == 200
    assert [event["message"] for event in response.json()] == ["first", "second"]
