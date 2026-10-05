import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.analysis_job import JobStatus

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class IncidentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    source: ShortText
    service: ShortText
    severity: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class ChaosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    fail_service: ShortText | None = None
    fail_attempts: int = Field(default=0, ge=0, le=2)
    delay_seconds: int = Field(default=0, ge=0, le=30)

    @model_validator(mode="after")
    def enabled_chaos_has_a_target(self) -> "ChaosConfig":
        if self.enabled and (
            self.fail_service is None or (self.fail_attempts < 1 and self.delay_seconds < 1)
        ):
            raise ValueError(
                "enabled chaos requires fail_service and either a failure or bounded delay"
            )
        return self


class IncidentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    environment: ShortText
    events: list[IncidentEvent] = Field(min_length=1)
    chaos: ChaosConfig | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def chaos_service_must_be_in_incident(self) -> "IncidentInput":
        if self.chaos and self.chaos.enabled:
            services = {event.service for event in self.events}
            if self.chaos.fail_service not in services:
                raise ValueError("chaos fail_service must name a service in the incident")
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    celery_task_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    incident: IncidentInput | None
    deterministic_summary: dict[str, Any] | None
    service_analyses: list[dict[str, Any]]
    result: dict[str, Any] | None
    error: str | None


class JobExecutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: uuid.UUID
    created_at: datetime
    event_type: str
    stage: str
    service: str | None
    celery_task_id: str | None
    attempt: int | None
    message: str
    metadata: dict[str, Any] | None = Field(validation_alias="metadata_json")
