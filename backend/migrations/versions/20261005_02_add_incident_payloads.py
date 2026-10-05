"""Add raw and normalized incident payloads.

Revision ID: 20261005_02
Revises: 20261005_01
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261005_02"
down_revision: str | None = "20261005_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column("incident", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("normalized_incident", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_jobs", "normalized_incident")
    op.drop_column("analysis_jobs", "incident")
