"""new-arrivals badge timestamp + media markers (intro/credits)

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-11

Two unrelated schema additions bundled for the ux-extras handoff:
  - users.last_seen_home_at: when the user last loaded the home page, used
    to count "new since your last visit" arrivals.
  - media_markers: detected intro/credits ranges per media file, feeding
    the Skip Intro / Skip Credits buttons in the player. Unique on
    (media_file_id, kind) so a re-analysis upserts rather than piling rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_home_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "media_markers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "media_file_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),  # intro | credits
        sa.Column("start_sec", sa.Integer(), nullable=False),
        sa.Column("end_sec", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="auto"),  # auto | manual
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("media_file_id", "kind", name="uq_media_markers_file_kind"),
    )
    op.create_index("ix_media_markers_file", "media_markers", ["media_file_id"])


def downgrade() -> None:
    op.drop_index("ix_media_markers_file", table_name="media_markers")
    op.drop_table("media_markers")
    op.drop_column("users", "last_seen_home_at")
