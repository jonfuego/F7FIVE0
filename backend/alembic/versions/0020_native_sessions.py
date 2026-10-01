"""native device sessions: platform, client_version, rotation grace

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-26

F7FIVE0 2.0 native client support. Adds device-session metadata columns
(`platform`, `client_version`) and the refresh-rotation grace-window
bookkeeping (`rotated_at`, `grace_used`) to `sessions`. `created_at` already
exists on the table (TimestampMixin), so it is not re-added here.

All columns are additive and nullable (or defaulted), so existing browser
and PWA rows are unaffected and their refresh TTLs are unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("platform", sa.String(length=32), nullable=True))
    op.add_column("sessions", sa.Column("client_version", sa.String(length=32), nullable=True))
    op.add_column("sessions", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "grace_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Drop the server default after backfilling existing rows to false; new
    # inserts set the value from the application layer (_issue_tokens).
    op.alter_column("sessions", "grace_used", server_default=None)


def downgrade() -> None:
    op.drop_column("sessions", "grace_used")
    op.drop_column("sessions", "rotated_at")
    op.drop_column("sessions", "client_version")
    op.drop_column("sessions", "platform")
