"""add sessions.client_type

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-02

Distinguishes browser refresh tokens from PWA refresh tokens so the auth
layer can hand the two different refresh TTLs. Existing rows backfill to
'browser' (preserves their current 30-day sliding behavior).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "client_type",
            sa.String(length=16),
            nullable=False,
            server_default="browser",
        ),
    )
    # Drop the server default after the backfill is applied so future
    # inserts come from the application layer (where _issue_tokens picks
    # 'browser' or 'pwa' explicitly).
    op.alter_column("sessions", "client_type", server_default=None)
    op.create_index(
        "ix_sessions_client_type",
        "sessions",
        ["client_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_client_type", table_name="sessions")
    op.drop_column("sessions", "client_type")
