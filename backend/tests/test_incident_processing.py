from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from celery.exceptions import Ignore
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.models.analysis_job import AnalysisJob, JobStatus
from app.schemas.analysis import IncidentReport, ServiceAnalysis
from app.tasks.process_incident import (
    WORKFLOW_STAGES,
    analyze_service,
    build_service_analysis_chord,
    dispatch_incident_workflow,
    fan_out_service_analyses,
    normalize_incident,
    normalize_incident_payload,
    summarize_events,
    summarize_incident,
    synthesize_incident_report,
)

RAW_INCIDENT = {
    "title": "Checkout API degradation",
    "environment": "production",
    "events": [
        {
            "timestamp": "2026-10-05T09:01:47+01:00",
            "source": " application ",
            "service": "payment-service",
            "severity": "error",
            "message": "Upstream checkout-api unavailable",
        },
        {
            "timestamp": "2026-10-05T08:01:12Z",
            "source": "synthetic   monitoring",
            "service": " checkout-api ",
            "severity": " warning ",
            "message": "HTTP latency threshold exceeded",
        },
        {
            "timestamp": "2026-10-05T08:02:10Z",
            "source": "application",
            "service": "checkout-api",
            "severity": "ERROR",
            "message": "HTTP 503 rate exceeded threshold",
        },
    ],
}

CHECKOUT_ANALYSIS = {
    "service": "checkout-api",
    "summary": "The checkout API returned elevated errors.",
    "probable_cause": "The supplied events suggest local or upstream failure.",
    "confidence": 0.78,
    "evidence": [
        {
            "timestamp": "2026-10-05T08:02:10Z",
            "observation": "HTTP 503 rate exceeded threshold",
        }
    ],
    "recommended_checks": ["Inspect service and upstream health"],
}

PAYMENT_ANALYSIS = {
    "service": "payment-service",
    "summary": "Payments observed checkout unavailability.",
    "probable_cause": "Checkout unavailability affected payment requests.",
    "confidence": 0.72,
    "evidence": [
        {
            "timestamp": "2026-10-05T08:01:47Z",
            "observation": "Upstream checkout-api unavailable",
        }
    ],
    "recommended_checks": ["Inspect checkout connectivity"],
}

FINAL_REPORT = {
    "executive_summary": "Checkout errors affected payment processing.",
    "probable_root_cause": "The evidence points to checkout unavailability.",
    "confidence": 0.8,
    "affected_services": ["checkout-api", "payment-service"],
    "impact": "Payment requests encountered upstream failures.",
    "timeline_summary": "Latency warnings preceded checkout errors.",
    "supporting_evidence": [
        "HTTP 503 rate exceeded threshold",
        "Upstream checkout-api unavailable",
    ],
    "recommended_actions": ["Inspect checkout health and payment connectivity"],
}


def test_celery_results_are_enabled_for_chord_coordination() -> None:
    assert celery_app.conf.result_backend == settings.celery_result_backend.get_secret_value()
    assert celery_app.conf.task_ignore_result is False


def test_normalize_and_group_services_deterministically() -> None:
    normalized = normalize_incident_payload(RAW_INCIDENT)

    assert [event["timestamp"] for event in normalized["events"]] == [
        "2026-10-05T08:01:12Z",
        "2026-10-05T08:01:47Z",
        "2026-10-05T08:02:10Z",
    ]
    assert normalized["events"][0]["source"] == "synthetic monitoring"
    assert normalized["events"][0]["service"] == "checkout-api"

    assert summarize_incident(normalized) == {
        "event_count": 3,
        "earliest_timestamp": "2026-10-05T08:01:12Z",
        "latest_timestamp": "2026-10-05T08:02:10Z",
        "services": ["checkout-api", "payment-service"],
        "sources": ["application", "synthetic monitoring"],
        "severity_counts": {"ERROR": 2, "WARNING": 1},
        "error_event_count": 2,
    }


def test_dispatch_builds_deterministic_chain_before_dynamic_fanout() -> None:
    job_id = "00000000-0000-0000-0000-000000000001"

    with patch("app.tasks.process_incident.chain") as celery_chain:
        result = dispatch_incident_workflow(job_id)

    stages = celery_chain.call_args.args
    assert [stage.task for stage in stages] == [
        "app.tasks.normalize_incident",
        "app.tasks.summarize_events",
        "app.tasks.fan_out_service_analyses",
    ]
    assert stages[0].args == (job_id,)
    assert stages[0].immutable is True
    celery_chain.return_value.apply_async.assert_called_once_with()
    assert result is celery_chain.return_value.apply_async.return_value


@pytest.mark.parametrize("services", [["one-service"], ["a", "b", "c"]])
def test_service_chord_has_one_immutable_task_per_distinct_service(
    services: list[str],
) -> None:
    job_id = "00000000-0000-0000-0000-000000000001"

    canvas = build_service_analysis_chord(job_id, services)

    header_tasks = list(canvas.tasks)
    assert len(header_tasks) == len(services)
    assert [task.task for task in header_tasks] == ["app.tasks.analyze_service"] * len(services)
    assert [task.args for task in header_tasks] == [(job_id, service) for service in services]
    assert all(task.immutable for task in header_tasks)
    assert canvas.body.task == "app.tasks.synthesize_incident_report"
    assert canvas.body.args == (job_id,)


@contextmanager
def _same_test_session(db_session: Session) -> Generator[Session, None, None]:
    yield db_session


def test_deterministic_tasks_update_durable_job_state(db_session: Session) -> None:
    job = AnalysisJob(incident=RAW_INCIDENT)
    db_session.add(job)
    db_session.commit()

    with patch(
        "app.tasks.process_incident.SessionLocal",
        side_effect=lambda: _same_test_session(db_session),
    ):
        normalized_state = normalize_incident.run(str(job.id))
        db_session.refresh(job)
        assert normalized_state == {"job_id": str(job.id)}
        assert job.status == JobStatus.PROCESSING
        assert job.progress == 20
        assert job.started_at is not None
        assert job.normalized_incident is not None

        summary_state = summarize_events.run(normalized_state)
        db_session.refresh(job)
        assert summary_state == {"job_id": str(job.id)}
        assert job.progress == 35
        assert job.deterministic_summary["services"] == [
            "checkout-api",
            "payment-service",
        ]


def test_analyze_service_loads_only_assigned_events(db_session: Session) -> None:
    normalized = normalize_incident_payload(RAW_INCIDENT)
    job = AnalysisJob(
        incident=RAW_INCIDENT,
        normalized_incident=normalized,
        status=JobStatus.PROCESSING,
        progress=40,
    )
    db_session.add(job)
    db_session.commit()

    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_test_session(db_session),
        ),
        patch(
            "app.tasks.process_incident.generate_service_analysis",
            return_value=ServiceAnalysis.model_validate(CHECKOUT_ANALYSIS),
        ) as generate,
    ):
        result = analyze_service.run(str(job.id), "checkout-api")

    assert result == CHECKOUT_ANALYSIS
    events = generate.call_args.kwargs["events"]
    assert len(events) == 2
    assert {event["service"] for event in events} == {"checkout-api"}


def test_fanout_replace_signal_does_not_mark_job_failed(db_session: Session) -> None:
    normalized = normalize_incident_payload(RAW_INCIDENT)
    job = AnalysisJob(
        incident=RAW_INCIDENT,
        normalized_incident=normalized,
        deterministic_summary=summarize_incident(normalized),
        status=JobStatus.PROCESSING,
        progress=35,
    )
    db_session.add(job)
    db_session.commit()

    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_test_session(db_session),
        ),
        patch.object(fan_out_service_analyses, "replace", side_effect=Ignore()),
        pytest.raises(Ignore),
    ):
        fan_out_service_analyses.run({"job_id": str(job.id)})

    db_session.refresh(job)
    assert job.status == JobStatus.PROCESSING
    assert job.progress == 40
    assert job.error is None


def test_successful_synthesis_persists_final_api_result(db_session: Session) -> None:
    normalized = normalize_incident_payload(RAW_INCIDENT)
    summary = summarize_incident(normalized)
    job = AnalysisJob(
        incident=RAW_INCIDENT,
        normalized_incident=normalized,
        deterministic_summary=summary,
        status=JobStatus.PROCESSING,
        progress=40,
    )
    db_session.add(job)
    db_session.commit()

    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_test_session(db_session),
        ),
        patch(
            "app.tasks.process_incident.generate_incident_report",
            return_value=IncidentReport.model_validate(FINAL_REPORT),
        ),
    ):
        returned_job_id = synthesize_incident_report.run(
            [CHECKOUT_ANALYSIS, PAYMENT_ANALYSIS], str(job.id)
        )

    db_session.refresh(job)
    assert returned_job_id == str(job.id)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100
    assert job.completed_at is not None
    assert job.service_analyses == [CHECKOUT_ANALYSIS, PAYMENT_ANALYSIS]
    assert job.result == {
        "deterministic_summary": summary,
        "service_analyses": [CHECKOUT_ANALYSIS, PAYMENT_ANALYSIS],
        "incident_report": FINAL_REPORT,
        "workflow": {"type": "celery_chain_group_chord", "stages": WORKFLOW_STAGES},
    }


def test_service_analysis_failure_marks_job_failed_and_reraises(db_session: Session) -> None:
    job = AnalysisJob(
        incident=RAW_INCIDENT,
        normalized_incident=normalize_incident_payload(RAW_INCIDENT),
        status=JobStatus.PROCESSING,
        progress=40,
    )
    db_session.add(job)
    db_session.commit()

    with (
        patch(
            "app.tasks.process_incident.SessionLocal",
            side_effect=lambda: _same_test_session(db_session),
        ),
        patch(
            "app.tasks.process_incident.generate_service_analysis",
            side_effect=ValueError("malformed model output"),
        ),
        pytest.raises(ValueError, match="malformed model output"),
    ):
        analyze_service.run(str(job.id), "checkout-api")

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert job.completed_at is not None
    assert job.error is not None
    assert "analyze_service failed" in job.error
    assert "malformed model output" in job.error
