"""media requests table (Overseerr-style request flow)

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-11

Adds the `requests` table backing the user request flow: a user asks for a
movie or series, an admin approves (which adds it to Radarr/Sonarr) or
denies, and the row flips to `available` automatically when the item lands
in the library during the next sync.

The partial unique index keeps one open request per (kind, external_id):
re-requesting the same title while a pending/approved/available row exists
is blocked, but a previously denied request does not stop a fresh ask.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("poster_url", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_requests_user_id", "requests", ["user_id"])
    op.create_index("ix_requests_status", "requests", ["status"])
    # One open request per (kind, external_id). Denied rows are excluded so a
    # rejected title can be requested again later.
    op.create_index(
        "uq_requests_kind_external_active",
        "requests",
        ["kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'denied'"),
    )


def downgrade() -> None:
    op.drop_index("uq_requests_kind_external_active", table_name="requests")
    op.drop_index("ix_requests_status", table_name="requests")
    op.drop_index("ix_requests_user_id", table_name="requests")
    op.drop_table("requests")
