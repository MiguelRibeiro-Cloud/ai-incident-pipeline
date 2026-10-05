"""Add reliability execution events and idempotent service results.

Revision ID: 20261005_04
Revises: 20261005_03
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261005_04"
down_revision: str | None = "20261005_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_analysis_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "service", name="uq_service_analysis_job_service"),
    )
    op.create_index(
        "ix_service_analysis_records_job_id",
        "service_analysis_records",
        ["job_id"],
        unique=False,
    )
    op.create_table(
        "job_execution_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("service", sa.String(length=100), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dedupe_key", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_job_execution_event_dedupe_key"),
    )
    op.create_index(
        "ix_job_execution_events_created_at",
        "job_execution_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_job_execution_events_event_type",
        "job_execution_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_job_execution_events_job_id", "job_execution_events", ["job_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_job_execution_events_job_id", table_name="job_execution_events")
    op.drop_index("ix_job_execution_events_event_type", table_name="job_execution_events")
    op.drop_index("ix_job_execution_events_created_at", table_name="job_execution_events")
    op.drop_table("job_execution_events")
    op.drop_index("ix_service_analysis_records_job_id", table_name="service_analysis_records")
    op.drop_table("service_analysis_records")
