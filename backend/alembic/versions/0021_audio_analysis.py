"""audio analysis: loudness, replaygain, waveform, similarity

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-27

Phase 2 "smart audio" backend. Additive: two new tables, no changes to any
existing table, so existing rows and every prior endpoint are untouched.

- `track_audio_analysis`: one row per track (unique track_id) holding EBU R128
  integrated loudness, ReplayGain-style track/album gain, a downsampled
  waveform peaks array (JSONB), the analysis version, and analyzed_at.
- `track_similarity`: top-N nearest-neighbor edges per track with a 0..1 score.

Both are populated out-of-band by `python -m app.cli analyze-audio`; the read
endpoints return nulls / empty lists until then.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "track_audio_analysis",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("integrated_lufs", sa.Float(), nullable=True),
        sa.Column("track_gain_db", sa.Float(), nullable=True),
        sa.Column("album_gain_db", sa.Float(), nullable=True),
        sa.Column("waveform_peaks", postgresql.JSONB(), nullable=True),
        sa.Column("analysis_version", sa.Integer(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", name="uq_track_audio_analysis_track"),
    )
    op.create_index(
        "ix_track_audio_analysis_track_id", "track_audio_analysis", ["track_id"],
    )
    op.create_index(
        "ix_track_audio_analysis_media_file", "track_audio_analysis", ["media_file_id"],
    )

    op.create_table(
        "track_similarity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("similar_track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["similar_track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", "similar_track_id", name="uq_track_similarity_pair"),
    )
    op.create_index(
        "ix_track_similarity_track_id", "track_similarity", ["track_id"],
    )
    op.create_index(
        "ix_track_similarity_track_score", "track_similarity", ["track_id", "score"],
    )


def downgrade() -> None:
    op.drop_index("ix_track_similarity_track_score", table_name="track_similarity")
    op.drop_index("ix_track_similarity_track_id", table_name="track_similarity")
    op.drop_table("track_similarity")
    op.drop_index("ix_track_audio_analysis_media_file", table_name="track_audio_analysis")
    op.drop_index("ix_track_audio_analysis_track_id", table_name="track_audio_analysis")
    op.drop_table("track_audio_analysis")
