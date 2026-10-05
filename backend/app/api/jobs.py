import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.execution import JobExecutionEvent, ServiceAnalysisRecord
from app.schemas.job import IncidentInput, JobExecutionEventResponse, JobResponse
from app.tasks.process_incident import dispatch_incident_workflow, record_workflow_started

router = APIRouter(prefix="/jobs", tags=["jobs"])
DbSession = Annotated[Session, Depends(get_db)]


def _job_response(job: AnalysisJob, db: Session) -> dict:
    records = list(
        db.scalars(
            select(ServiceAnalysisRecord)
            .where(ServiceAnalysisRecord.job_id == job.id)
            .order_by(ServiceAnalysisRecord.service)
        )
    )
    progress = job.progress
    if job.status == JobStatus.PROCESSING and job.deterministic_summary:
        service_count = len(job.deterministic_summary.get("services", []))
        if service_count:
            progress = max(progress, min(80, 40 + int(40 * len(records) / service_count)))
    return {
        "id": job.id,
        "status": job.status,
        "progress": progress,
        "celery_task_id": job.celery_task_id,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "incident": job.incident,
        "deterministic_summary": job.deterministic_summary,
        "service_analyses": [record.analysis for record in records] or (job.service_analyses or []),
        "result": job.result,
        "error": job.error,
    }


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(incident: IncidentInput, db: DbSession) -> dict:
    if incident.chaos and incident.chaos.enabled and not settings.enable_chaos_demo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chaos demo mode is disabled by server configuration",
        )
    job = AnalysisJob(
        status=JobStatus.QUEUED,
        progress=0,
        incident=incident.model_dump(mode="json"),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # There is intentionally a small consistency gap between this database commit
    # and broker publication. A transactional outbox belongs in a later stage.
    record_workflow_started(str(job.id), db)
    workflow_result = dispatch_incident_workflow(str(job.id))
    job.celery_task_id = workflow_result.id
    db.commit()
    db.refresh(job)
    return _job_response(job, db)


@router.get("", response_model=list[JobResponse])
def list_jobs(db: DbSession) -> list[dict]:
    statement = select(AnalysisJob).order_by(AnalysisJob.created_at.desc()).limit(100)
    return [_job_response(job, db) for job in db.scalars(statement)]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, db: DbSession) -> dict:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_response(job, db)


@router.get("/{job_id}/events", response_model=list[JobExecutionEventResponse])
def get_job_events(job_id: uuid.UUID, db: DbSession) -> list[JobExecutionEvent]:
    if db.get(AnalysisJob, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    statement = (
        select(JobExecutionEvent)
        .where(JobExecutionEvent.job_id == job_id)
        .order_by(JobExecutionEvent.created_at, JobExecutionEvent.id)
    )
    return list(db.scalars(statement))
