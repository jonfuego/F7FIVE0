"""add offset_bucket to transcode_sessions and transcode_cache

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-18

Support resume-from-offset HLS transcodes. A single (media_file, variant)
pair can now correspond to multiple on-disk cache dirs, one per bucketed
resume point, so both the active-session table and the cache-accounting
table need a new column and transcode_cache's unique constraint needs to
grow to include it.

Existing rows get offset_bucket=0 via the column default, which matches
the new behavior of "start from the beginning" and keeps the active
admin panel's active-streams display unchanged for pre-migration rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # transcode_sessions: simple ADD COLUMN.
    op.add_column(
        "transcode_sessions",
        sa.Column(
            "offset_bucket",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # transcode_cache: ADD COLUMN, then swap the unique constraint so
    # (media_file_id, variant, offset_bucket) is the new uniqueness key.
    # Drop-then-create lets us rename the constraint at the same time.
    op.add_column(
        "transcode_cache",
        sa.Column(
            "offset_bucket",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.drop_constraint(
        "uq_transcode_cache_file_variant",
        "transcode_cache",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_transcode_cache_file_variant_bucket",
        "transcode_cache",
        ["media_file_id", "variant", "offset_bucket"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_transcode_cache_file_variant_bucket",
        "transcode_cache",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_transcode_cache_file_variant",
        "transcode_cache",
        ["media_file_id", "variant"],
    )
    op.drop_column("transcode_cache", "offset_bucket")
    op.drop_column("transcode_sessions", "offset_bucket")
