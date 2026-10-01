"""add track_plays table

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-30

Per-user audio play log. The MiniPlayer writes a row when a track
finishes (`<audio>` ended event) or when the user skips after at least
30 seconds of playback. `completed` is true when ms_played > 90% of
duration_sec * 1000; otherwise false. Powers the most-played /
never-played / recently-played / artist-radio kinds in the
auto-playlist module.

The two indexes match the read patterns:
- (user_id, track_id) for "has the user played this track" lookups
- (user_id, played_at DESC) for the recently-played feed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "track_plays",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "played_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ms_played", sa.Integer(), nullable=False),
        sa.Column(
            "completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_track_plays_user_track",
        "track_plays",
        ["user_id", "track_id"],
    )
    op.create_index(
        "ix_track_plays_user_at_desc",
        "track_plays",
        ["user_id", sa.text("played_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_track_plays_user_at_desc", table_name="track_plays")
    op.drop_index("ix_track_plays_user_track", table_name="track_plays")
    op.drop_table("track_plays")
