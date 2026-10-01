"""add playback_queues

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-02

Server-backed audio queue. One row per user (PK on user_id). Mirrors the
shape the client kept in localStorage so the existing reducer can hydrate
unchanged. `last_writer_id` is an opaque per-tab string the UI uses to
suppress echo from its own debounced writes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "playback_queues",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "items",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("current_index", sa.Integer, nullable=True),
        sa.Column(
            "repeat_mode",
            sa.String(length=8),
            nullable=False,
            server_default="off",
        ),
        sa.Column("last_writer_id", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("playback_queues")
