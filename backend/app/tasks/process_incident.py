import logging
import random
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Never, TypeVar, cast

from celery import chain, chord, group
from celery.exceptions import Ignore
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.celery_app import celery_app
from app.config import settings
from app.db.session import SessionLocal
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.execution import ExecutionEventType, JobExecutionEvent, ServiceAnalysisRecord
from app.schemas.analysis import ServiceAnalysis
from app.schemas.job import IncidentInput
from app.services.llm import generate_incident_report, generate_service_analysis
from app.services.llm_errors import LLMError, TransientLLMError

logger = logging.getLogger(__name__)
StageInput = str | dict[str, Any]
StageFunction = TypeVar("StageFunction", bound=Callable[..., Any])
MAX_AI_RETRIES = 3
MAX_RETRY_DELAY_SECONDS = 30
WORKFLOW_STAGES = [
    "normalize_incident",
    "summarize_events",
    "analyze_service (group)",
    "synthesize_incident_report (chord callback)",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalized_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_incident_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize an incident without touching infrastructure."""
    incident = IncidentInput.model_validate(payload)
    events = [
        {
            "timestamp": event.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "source": _normalized_whitespace(event.source),
            "service": _normalized_whitespace(event.service),
            "severity": event.severity.upper(),
            "message": event.message,
        }
        for event in incident.events
    ]
    events.sort(key=lambda event: event["timestamp"])
    return {"title": incident.title, "environment": incident.environment, "events": events}


def summarize_incident(normalized_incident: dict[str, Any]) -> dict[str, Any]:
    """Build the deterministic analysis used before AI fan-out."""
    events = normalized_incident.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("normalized incident must contain at least one event")
    severity_counts: dict[str, int] = {}
    for event in events:
        severity = str(event["severity"])
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    return {
        "event_count": len(events),
        "earliest_timestamp": events[0]["timestamp"],
        "latest_timestamp": events[-1]["timestamp"],
        "services": sorted({str(event["service"]) for event in events}),
        "sources": sorted({str(event["source"]) for event in events}),
        "severity_counts": dict(sorted(severity_counts.items())),
        "error_event_count": severity_counts.get("ERROR", 0),
    }


def _extract_job_id(stage_input: StageInput) -> str:
    if isinstance(stage_input, str):
        return stage_input
    job_id = stage_input.get("job_id")
    if not isinstance(job_id, str):
        raise ValueError("workflow state is missing job_id")
    return job_id


def _parse_job_id(job_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(job_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid analysis job ID: {job_id}") from exc


def _get_job(db: Any, job_id: str) -> AnalysisJob:
    job = db.get(AnalysisJob, _parse_job_id(job_id))
    if job is None:
        raise ValueError(f"Analysis job {job_id} does not exist")
    return job


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "AI response failed structured-output validation"
    if isinstance(exc, LLMError):
        return str(exc)
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)[:300]
    return "unexpected internal error"


def _record_event(
    job_id: str,
    event_type: ExecutionEventType,
    stage: str,
    message: str,
    *,
    service: str | None = None,
    celery_task_id: str | None = None,
    attempt: int | None = None,
    metadata: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> bool:
    event = JobExecutionEvent(
        job_id=_parse_job_id(job_id),
        event_type=event_type,
        stage=stage,
        service=service,
        celery_task_id=celery_task_id,
        attempt=attempt,
        message=message,
        metadata_json=metadata,
        dedupe_key=f"{job_id}:{dedupe_key}" if dedupe_key else None,
    )
    with SessionLocal() as db:
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if dedupe_key:
                return False
            raise
    return True


def _mark_job_failed(job_id: str, stage: str, exc: Exception) -> None:
    changed = False
    message = f"{stage} failed: {type(exc).__name__}: {_safe_error_message(exc)}"
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED}:
            job.status = JobStatus.FAILED
            job.completed_at = utc_now()
            job.error = message
            changed = True
            db.commit()
    if changed:
        _record_event(
            job_id,
            ExecutionEventType.JOB_FAILED,
            stage,
            message,
            dedupe_key="job-failed",
        )


def _record_task_failure(
    job_id: str,
    stage: str,
    exc: Exception,
    *,
    service: str | None = None,
    task_id: str | None = None,
    attempt: int | None = None,
) -> None:
    _record_event(
        job_id,
        ExecutionEventType.TASK_FAILED,
        stage,
        _safe_error_message(exc),
        service=service,
        celery_task_id=task_id,
        attempt=attempt,
        dedupe_key=f"task-failed:{stage}:{service or '-'}:{attempt or '-'}:{task_id or 'direct'}",
    )
    _mark_job_failed(job_id, stage, exc)


def fail_job_on_error(job_id_position: int = 0) -> Callable[[StageFunction], StageFunction]:
    """Persist terminal deterministic-stage failure while preserving Celery signals."""

    def decorator(function: StageFunction) -> StageFunction:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return function(*args, **kwargs)
            except Ignore:
                raise
            except Exception as exc:
                try:
                    job_id = _extract_job_id(args[job_id_position])
                    _record_task_failure(job_id, function.__name__, exc)
                except Exception:
                    logger.exception(
                        "Could not persist failure for workflow stage %s", function.__name__
                    )
                raise

        return cast(StageFunction, wrapped)

    return decorator


def _task_context(task: Any) -> tuple[str | None, int, bool]:
    request = task.request
    task_id = getattr(request, "id", None)
    attempt = int(getattr(request, "retries", 0)) + 1
    delivery_info = getattr(request, "delivery_info", None) or {}
    return task_id, attempt, bool(delivery_info.get("redelivered"))


def _record_task_start(
    job_id: str, stage: str, task: Any, *, service: str | None = None
) -> tuple[str | None, int]:
    task_id, attempt, redelivered = _task_context(task)
    identity = task_id or "direct"
    if redelivered:
        _record_event(
            job_id,
            ExecutionEventType.TASK_REDELIVERED,
            stage,
            "Broker redelivered an unacknowledged task after worker loss",
            service=service,
            celery_task_id=task_id,
            attempt=attempt,
            dedupe_key=f"redelivered:{stage}:{service or '-'}:{attempt}:{identity}",
        )
    _record_event(
        job_id,
        ExecutionEventType.TASK_STARTED,
        stage,
        f"Started {stage}",
        service=service,
        celery_task_id=task_id,
        attempt=attempt,
        dedupe_key=f"task-started:{stage}:{service or '-'}:{attempt}:{identity}",
    )
    return task_id, attempt


def retry_delay_seconds(retries: int) -> float:
    """Exponential delay with bounded positive jitter (about 1-2s initially)."""
    base = min(2**retries, MAX_RETRY_DELAY_SECONDS)
    return min(random.uniform(base, base * 2), MAX_RETRY_DELAY_SECONDS)


def _retry_or_fail(
    task: Any,
    exc: TransientLLMError,
    job_id: str,
    stage: str,
    *,
    service: str | None = None,
) -> Never:
    task_id, attempt, _ = _task_context(task)
    if int(task.request.retries) < MAX_AI_RETRIES:
        delay = retry_delay_seconds(int(task.request.retries))
        _record_event(
            job_id,
            ExecutionEventType.RETRY_SCHEDULED,
            stage,
            f"Transient AI failure; retry scheduled in {delay:.2f}s",
            service=service,
            celery_task_id=task_id,
            attempt=attempt,
            metadata={"countdown_seconds": delay, "next_attempt": attempt + 1},
            dedupe_key=f"retry:{stage}:{service or '-'}:{attempt}:{task_id or 'direct'}",
        )
        raise task.retry(exc=exc, countdown=delay, max_retries=MAX_AI_RETRIES)
    _record_task_failure(job_id, stage, exc, service=service, task_id=task_id, attempt=attempt)
    raise exc


def _service_result(db: Any, job_id: str, service: str) -> ServiceAnalysisRecord | None:
    return db.scalar(
        select(ServiceAnalysisRecord).where(
            ServiceAnalysisRecord.job_id == _parse_job_id(job_id),
            ServiceAnalysisRecord.service == service,
        )
    )


def _store_service_result(
    job_id: str,
    service: str,
    analysis: dict[str, Any],
    task_id: str | None,
    attempt: int,
) -> dict[str, Any]:
    """Insert the first successful result atomically and reuse it thereafter."""
    now = utc_now()
    values = {
        "id": uuid.uuid4(),
        "job_id": _parse_job_id(job_id),
        "service": service,
        "analysis": analysis,
        "celery_task_id": task_id,
        "attempt": attempt,
        "created_at": now,
        "updated_at": now,
    }
    with SessionLocal() as db:
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = postgresql_insert(ServiceAnalysisRecord).values(**values)
        elif dialect == "sqlite":
            statement = sqlite_insert(ServiceAnalysisRecord).values(**values)
        else:  # pragma: no cover
            raise RuntimeError(f"unsupported database dialect for idempotent insert: {dialect}")
        statement = statement.on_conflict_do_nothing(index_elements=["job_id", "service"])
        db.execute(statement)
        db.commit()
        record = _service_result(db, job_id, service)
        if record is None:
            raise RuntimeError("service analysis could not be persisted")
        return record.analysis


def _load_service_results(job_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        records = db.scalars(
            select(ServiceAnalysisRecord)
            .where(ServiceAnalysisRecord.job_id == _parse_job_id(job_id))
            .order_by(ServiceAnalysisRecord.service)
        )
        return [record.analysis for record in records]


def _chaos_should_fail(job: AnalysisJob, service: str, attempt: int) -> bool:
    if not settings.enable_chaos_demo or not job.incident:
        return False
    chaos = job.incident.get("chaos")
    if not isinstance(chaos, dict) or not chaos.get("enabled"):
        return False
    return chaos.get("fail_service") == service and attempt <= int(chaos.get("fail_attempts", 0))


def _chaos_delay_seconds(job: AnalysisJob, service: str) -> int:
    if not settings.enable_chaos_demo or not job.incident:
        return 0
    chaos = job.incident.get("chaos")
    if not isinstance(chaos, dict) or not chaos.get("enabled"):
        return 0
    if chaos.get("fail_service") != service:
        return 0
    return min(max(int(chaos.get("delay_seconds", 0)), 0), 30)


@celery_app.task(name="app.tasks.normalize_incident")
@fail_job_on_error()
def normalize_incident(job_id: str) -> dict[str, str]:
    _record_event(
        job_id,
        ExecutionEventType.TASK_STARTED,
        "normalize_incident",
        "Started incident normalization",
        dedupe_key="normalize-started",
    )
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            return {"job_id": job_id}
        if job.incident is None:
            raise ValueError("analysis job has no incident payload")
        job.status = JobStatus.PROCESSING
        job.started_at = job.started_at or utc_now()
        job.error = None
        job.normalized_incident = normalize_incident_payload(job.incident)
        job.progress = max(job.progress, 20)
        db.commit()
    return {"job_id": job_id}


@celery_app.task(name="app.tasks.summarize_events")
@fail_job_on_error()
def summarize_events(stage_state: dict[str, Any]) -> dict[str, str]:
    job_id = _extract_job_id(stage_state)
    _record_event(
        job_id,
        ExecutionEventType.TASK_STARTED,
        "summarize_events",
        "Started deterministic incident summary",
        dedupe_key="summarize-started",
    )
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            return {"job_id": job_id}
        if job.normalized_incident is None:
            raise ValueError("analysis job has no normalized incident")
        job.deterministic_summary = summarize_incident(job.normalized_incident)
        job.progress = max(job.progress, 35)
        db.commit()
    return {"job_id": job_id}


def build_service_analysis_chord(job_id: str, services: list[str]) -> Any:
    if not services:
        raise ValueError("cannot analyze an incident without services")
    header = group(analyze_service.si(job_id, service) for service in services)
    callback = synthesize_incident_report.s(job_id)
    return chord(header, callback)


@celery_app.task(bind=True, name="app.tasks.fan_out_service_analyses")
@fail_job_on_error(job_id_position=1)
def fan_out_service_analyses(self: Any, stage_state: dict[str, Any]) -> Any:
    job_id = _extract_job_id(stage_state)
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            return {"job_id": job_id}
        summary = job.deterministic_summary
        if summary is None:
            raise ValueError("analysis job has no deterministic summary")
        services = summary.get("services")
        if not isinstance(services, list) or not all(isinstance(item, str) for item in services):
            raise ValueError("deterministic summary has invalid services")
        job.progress = max(job.progress, 40)
        db.commit()
    return self.replace(build_service_analysis_chord(job_id, services))


@celery_app.task(
    bind=True,
    name="app.tasks.analyze_service",
    max_retries=MAX_AI_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def analyze_service(self: Any, job_id: str, service: str) -> dict[str, Any]:
    task_id, attempt = _record_task_start(job_id, "analyze_service", self, service=service)
    logger.info(
        "Starting service analysis job_id=%s service=%s attempt=%s", job_id, service, attempt
    )
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        cached = _service_result(db, job_id, service)
        if cached is not None:
            return cached.analysis
        if job.status == JobStatus.COMPLETED:
            raise RuntimeError("completed job is missing its persisted service analysis")
        if job.status == JobStatus.FAILED:
            raise RuntimeError("refusing to analyze an already failed job")
        if job.normalized_incident is None:
            exc = ValueError("analysis job has no normalized incident")
            _record_task_failure(
                job_id, "analyze_service", exc, service=service, task_id=task_id, attempt=attempt
            )
            raise exc
        events = [
            event
            for event in job.normalized_incident.get("events", [])
            if event.get("service") == service
        ]
        if not events:
            exc = ValueError(f"analysis job has no events for service {service!r}")
            _record_task_failure(
                job_id, "analyze_service", exc, service=service, task_id=task_id, attempt=attempt
            )
            raise exc
        incident_context = {
            "title": job.normalized_incident.get("title"),
            "environment": job.normalized_incident.get("environment"),
        }
        inject_chaos = _chaos_should_fail(job, service, attempt)
        chaos_delay = _chaos_delay_seconds(job, service)

    if inject_chaos:
        inserted = _record_event(
            job_id,
            ExecutionEventType.CHAOS_FAILURE_INJECTED,
            "analyze_service",
            "Injected a deterministic transient provider failure before the AI request",
            service=service,
            celery_task_id=task_id,
            attempt=attempt,
            dedupe_key=f"chaos:{service}:{attempt}",
        )
        if inserted:
            _retry_or_fail(
                self,
                TransientLLMError("simulated temporary AI provider failure"),
                job_id,
                "analyze_service",
                service=service,
            )

    if chaos_delay:
        _record_event(
            job_id,
            ExecutionEventType.CHAOS_DELAY_INJECTED,
            "analyze_service",
            f"Holding the demo task for {chaos_delay}s before the AI request",
            service=service,
            celery_task_id=task_id,
            attempt=attempt,
            metadata={"delay_seconds": chaos_delay},
            dedupe_key=f"chaos-delay:{service}:{attempt}:{task_id or 'direct'}",
        )
        time.sleep(chaos_delay)

    _record_event(
        job_id,
        ExecutionEventType.AI_REQUEST_STARTED,
        "analyze_service",
        "Started Gemini service analysis request",
        service=service,
        celery_task_id=task_id,
        attempt=attempt,
        dedupe_key=f"ai-request:analyze:{service}:{attempt}:{task_id or 'direct'}",
    )
    try:
        generated = generate_service_analysis(
            service=service, incident_context=incident_context, events=events
        ).model_dump(mode="json")
    except TransientLLMError as exc:
        _retry_or_fail(self, exc, job_id, "analyze_service", service=service)
    except Exception as exc:
        _record_task_failure(
            job_id, "analyze_service", exc, service=service, task_id=task_id, attempt=attempt
        )
        raise

    analysis = _store_service_result(job_id, service, generated, task_id, attempt)
    _record_event(
        job_id,
        ExecutionEventType.TASK_SUCCEEDED,
        "analyze_service",
        "Service analysis succeeded",
        service=service,
        celery_task_id=task_id,
        attempt=attempt,
        dedupe_key=f"service-succeeded:{service}",
    )
    logger.info("Completed service analysis job_id=%s service=%s", job_id, service)
    return analysis


@celery_app.task(
    bind=True,
    name="app.tasks.synthesize_incident_report",
    max_retries=MAX_AI_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def synthesize_incident_report(
    self: Any, service_analysis_results: list[dict[str, Any]], job_id: str
) -> str:
    task_id, attempt = _record_task_start(job_id, "synthesize_incident_report", self)
    logger.info("Starting final synthesis job_id=%s attempt=%s", job_id, attempt)
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        if job.status == JobStatus.COMPLETED:
            return job_id
        if job.status == JobStatus.FAILED:
            raise RuntimeError("refusing to complete an already failed analysis job")
        if job.normalized_incident is None or job.deterministic_summary is None:
            exc = ValueError("analysis job is missing synthesis inputs")
            _record_task_failure(
                job_id, "synthesize_incident_report", exc, task_id=task_id, attempt=attempt
            )
            raise exc
        normalized_incident = job.normalized_incident
        deterministic_summary = job.deterministic_summary

    try:
        header_analyses = [
            ServiceAnalysis.model_validate(item).model_dump(mode="json")
            for item in service_analysis_results
        ]
        expected_services = set(deterministic_summary.get("services", []))
        analyzed_services = {analysis["service"] for analysis in header_analyses}
        if len(header_analyses) != len(analyzed_services) or analyzed_services != expected_services:
            raise ValueError("service analysis results do not match incident services")
    except Exception as exc:
        _record_task_failure(
            job_id, "synthesize_incident_report", exc, task_id=task_id, attempt=attempt
        )
        raise

    for analysis in header_analyses:
        _store_service_result(job_id, analysis["service"], analysis, None, attempt)
    analyses = _load_service_results(job_id)
    with SessionLocal() as db:
        job = _get_job(db, job_id)
        if job.status == JobStatus.COMPLETED:
            return job_id
        job.service_analyses = analyses
        job.progress = max(job.progress, 85)
        db.commit()

    _record_event(
        job_id,
        ExecutionEventType.SYNTHESIS_STARTED,
        "synthesize_incident_report",
        "Started final Gemini synthesis",
        celery_task_id=task_id,
        attempt=attempt,
        dedupe_key=f"synthesis-started:{attempt}:{task_id or 'direct'}",
    )
    _record_event(
        job_id,
        ExecutionEventType.AI_REQUEST_STARTED,
        "synthesize_incident_report",
        "Started Gemini incident report request",
        celery_task_id=task_id,
        attempt=attempt,
        dedupe_key=f"ai-request:synthesis:{attempt}:{task_id or 'direct'}",
    )
    try:
        report = generate_incident_report(
            normalized_incident=normalized_incident,
            deterministic_summary=deterministic_summary,
            service_analyses=analyses,
        ).model_dump(mode="json")
    except TransientLLMError as exc:
        _retry_or_fail(self, exc, job_id, "synthesize_incident_report")
    except Exception as exc:
        _record_task_failure(
            job_id, "synthesize_incident_report", exc, task_id=task_id, attempt=attempt
        )
        raise

    result = {
        "deterministic_summary": deterministic_summary,
        "service_analyses": analyses,
        "incident_report": report,
        "workflow": {"type": "celery_chain_group_chord", "stages": WORKFLOW_STAGES},
    }
    with SessionLocal() as db:
        completion = db.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.id == _parse_job_id(job_id),
                AnalysisJob.status == JobStatus.PROCESSING,
            )
            .values(
                result=result,
                service_analyses=analyses,
                status=JobStatus.COMPLETED,
                progress=100,
                completed_at=utc_now(),
                error=None,
            )
        )
        db.commit()
        completed_here = completion.rowcount == 1
    if completed_here:
        _record_event(
            job_id,
            ExecutionEventType.TASK_SUCCEEDED,
            "synthesize_incident_report",
            "Final synthesis succeeded",
            celery_task_id=task_id,
            attempt=attempt,
            dedupe_key="synthesis-succeeded",
        )
        _record_event(
            job_id,
            ExecutionEventType.JOB_COMPLETED,
            "synthesize_incident_report",
            "Analysis job completed",
            celery_task_id=task_id,
            attempt=attempt,
            dedupe_key="job-completed",
        )
    logger.info("Completed final synthesis job_id=%s", job_id)
    return job_id


def record_workflow_started(job_id: str, db: Any | None = None) -> None:
    event = JobExecutionEvent(
        job_id=_parse_job_id(job_id),
        event_type=ExecutionEventType.WORKFLOW_STARTED,
        stage="workflow",
        message="Incident analysis workflow submitted",
        dedupe_key=f"{job_id}:workflow-started",
    )
    if db is not None:
        db.add(event)
        db.commit()
        return
    _record_event(
        job_id,
        ExecutionEventType.WORKFLOW_STARTED,
        "workflow",
        "Incident analysis workflow submitted",
        dedupe_key="workflow-started",
    )


def dispatch_incident_workflow(job_id: str) -> Any:
    workflow = chain(
        normalize_incident.si(job_id), summarize_events.s(), fan_out_service_analyses.s()
    )
    return workflow.apply_async()
