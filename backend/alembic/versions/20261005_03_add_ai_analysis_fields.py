"""Add durable AI analysis fields.

Revision ID: 20261005_03
Revises: 20261005_02
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261005_03"
down_revision: str | None = "20261005_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column("deterministic_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("service_analyses", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_jobs", "service_analyses")
    op.drop_column("analysis_jobs", "deterministic_summary")
