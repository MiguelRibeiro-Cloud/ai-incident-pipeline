import uuid
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.models.analysis_job import AnalysisJob, JobStatus

INCIDENT = {
    "title": "Checkout API degradation",
    "environment": "production",
    "events": [
        {
            "timestamp": "2026-10-05T08:01:47Z",
            "source": "application",
            "service": "payment-service",
            "severity": "ERROR",
            "message": "Upstream checkout-api unavailable",
        },
        {
            "timestamp": "2026-10-05T08:01:12Z",
            "source": "monitoring",
            "service": "checkout-api",
            "severity": "ERROR",
            "message": "HTTP 503 rate exceeded threshold",
        },
    ],
}


def test_create_job_persists_incident_and_dispatches_only_job_id(
    client: TestClient, db_session
) -> None:
    async_result = Mock(id="celery-workflow-123")

    with patch("app.api.jobs.dispatch_incident_workflow", return_value=async_result) as dispatch:
        response = client.post("/api/v1/jobs", json=INCIDENT)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["progress"] == 0
    assert body["celery_task_id"] == "celery-workflow-123"
    assert body["incident"] == INCIDENT
    dispatch.assert_called_once_with(body["id"])

    persisted_job = db_session.get(AnalysisJob, uuid.UUID(body["id"]))
    assert persisted_job is not None
    assert persisted_job.incident == INCIDENT


def test_create_job_rejects_empty_events(client: TestClient) -> None:
    invalid_incident = {**INCIDENT, "events": []}

    response = client.post("/api/v1/jobs", json=invalid_incident)

    assert response.status_code == 422


def test_create_job_rejects_missing_body(client: TestClient) -> None:
    response = client.post("/api/v1/jobs")

    assert response.status_code == 422


def test_create_job_rejects_timestamp_without_timezone(client: TestClient) -> None:
    invalid_incident = {
        **INCIDENT,
        "events": [{**INCIDENT["events"][0], "timestamp": "2026-10-05T08:01:47"}],
    }

    response = client.post("/api/v1/jobs", json=invalid_incident)

    assert response.status_code == 422


def test_retrieve_existing_job_has_expected_schema(client: TestClient, db_session) -> None:
    job = AnalysisJob(status=JobStatus.PROCESSING, progress=25, incident=INCIDENT)
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "PROCESSING"
    assert body["progress"] == 25
    assert body["incident"] == INCIDENT
    assert set(body) == {
        "id",
        "status",
        "progress",
        "celery_task_id",
        "created_at",
        "started_at",
        "completed_at",
        "incident",
        "deterministic_summary",
        "service_analyses",
        "result",
        "error",
    }


def test_retrieve_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_completed_job_exposes_stage_three_result_shape(client: TestClient, db_session) -> None:
    result = {
        "deterministic_summary": {
            "event_count": 2,
            "services": ["checkout-api", "payment-service"],
            "severity_counts": {"ERROR": 2},
        },
        "service_analyses": [
            {
                "service": "checkout-api",
                "summary": "Elevated errors were observed.",
                "probable_cause": "Service failure is likely.",
                "confidence": 0.8,
                "evidence": [],
                "recommended_checks": ["Inspect service health"],
            }
        ],
        "incident_report": {
            "executive_summary": "Checkout errors affected payments.",
            "probable_root_cause": "Checkout became unavailable.",
            "confidence": 0.8,
            "affected_services": ["checkout-api", "payment-service"],
            "impact": "Payment requests failed.",
            "timeline_summary": "Checkout errors preceded payment failures.",
            "supporting_evidence": ["HTTP 503 rate exceeded threshold"],
            "recommended_actions": ["Inspect checkout health"],
        },
    }
    job = AnalysisJob(
        status=JobStatus.COMPLETED,
        progress=100,
        incident=INCIDENT,
        result=result,
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["result"] == result


def test_list_jobs_newest_first(client: TestClient, db_session) -> None:
    first = AnalysisJob(incident=INCIDENT)
    db_session.add(first)
    db_session.commit()
    second = AnalysisJob(incident=INCIDENT)
    db_session.add(second)
    db_session.commit()

    response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(second.id), str(first.id)]
