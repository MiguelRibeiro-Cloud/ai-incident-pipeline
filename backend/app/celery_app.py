from celery import Celery

from app.config import settings

celery_app = Celery(
    "ai_incident_pipeline",
    broker=settings.celery_broker_url.get_secret_value(),
    backend=settings.celery_result_backend.get_secret_value(),
    include=["app.tasks.process_incident"],
)
celery_app.conf.update(
    # Chords use task results to count completed header tasks and supply their
    # validated outputs to the callback. PostgreSQL remains the durable source
    # of truth for application job state and API results.
    task_ignore_result=False,
    result_expires=3_600,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Long AI calls should be distributed fairly instead of being reserved in
    # batches by a worker. Late acknowledgement remains configured per task.
    worker_prefetch_multiplier=1,
)
