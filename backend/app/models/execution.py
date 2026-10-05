import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionEventType(StrEnum):
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    TASK_STARTED = "TASK_STARTED"
    AI_REQUEST_STARTED = "AI_REQUEST_STARTED"
    CHAOS_FAILURE_INJECTED = "CHAOS_FAILURE_INJECTED"
    CHAOS_DELAY_INJECTED = "CHAOS_DELAY_INJECTED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    TASK_SUCCEEDED = "TASK_SUCCEEDED"
    TASK_FAILED = "TASK_FAILED"
    TASK_REDELIVERED = "TASK_REDELIVERED"
    SYNTHESIS_STARTED = "SYNTHESIS_STARTED"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_FAILED = "JOB_FAILED"


class ServiceAnalysisRecord(Base):
    __tablename__ = "service_analysis_records"
    __table_args__ = (
        UniqueConstraint("job_id", "service", name="uq_service_analysis_job_service"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    analysis: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class JobExecutionEvent(Base):
    __tablename__ = "job_execution_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_job_execution_event_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    event_type: Mapped[ExecutionEventType] = mapped_column(String(40), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    service: Mapped[str | None] = mapped_column(String(100), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
