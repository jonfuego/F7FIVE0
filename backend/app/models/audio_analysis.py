"""Per-track audio analysis: loudness, ReplayGain, waveform, and similarity.

Phase 2 "smart audio" backend. Analysis is expensive (one ffmpeg pass per
file) and runs out-of-band via `python -m app.cli analyze-audio`, never on
the request path. The read endpoints join a track to its analysis row and
return nulls when a track has not been analyzed yet.

Two tables:

- `track_audio_analysis`: one row per track. Keyed by `track_id` (unique) so
  the read endpoints (`/api/tracks/{track_id}/loudness|waveform`) resolve with
  a single PK-shaped lookup. `media_file_id` is carried denormalized so the CLI
  can skip already-analyzed files and so a re-scan that swaps the physical file
  can invalidate the row.

- `track_similarity`: top-N nearest neighbors per track. `(track_id,
  similar_track_id)` is unique; `score` is 0..1 (higher = closer). Stored as
  edges rather than a JSON blob so `/api/tracks/{track_id}/similar` and
  `track-radio` can ORDER BY score and JOIN the playable pool directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


# Bumped whenever the analysis algorithm changes in a way that makes older
# rows stale. The CLI writes the current version onto every row it produces;
# a future `--min-version` sweep can re-analyze anything below the floor.
ANALYSIS_VERSION = 1


class TrackAudioAnalysis(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "track_audio_analysis"

    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # The physical file the analysis was computed from. Denormalized so the
    # CLI can detect a swapped file and re-analyze. Nullable because a stale
    # analysis row can outlive its media file (soft-deleted / missing).
    media_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="SET NULL"),
        nullable=True,
    )

    # EBU R128 integrated loudness, in LUFS (typically negative, e.g. -14.2).
    integrated_lufs: Mapped[Optional[float]] = mapped_column(Float)
    # ReplayGain-style adjustments in dB. `track_gain_db` targets -16 LUFS per
    # track; `album_gain_db` targets the album's integrated loudness so intra-
    # album dynamics are preserved. Both are attenuation-only (<= 0) unless a
    # headroom flag is passed to the analyzer.
    track_gain_db: Mapped[Optional[float]] = mapped_column(Float)
    album_gain_db: Mapped[Optional[float]] = mapped_column(Float)

    # Downsampled peak envelope for the scrubber: an array of ints 0..100,
    # up to ~1000 buckets. JSONB on Postgres, JSON on SQLite (see conftest).
    waveform_peaks: Mapped[Optional[list]] = mapped_column(JSONB)

    analysis_version: Mapped[Optional[int]] = mapped_column(Integer)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )

    __table_args__ = (
        Index("ix_track_audio_analysis_media_file", "media_file_id"),
    )


class TrackSimilarity(UUIDPKMixin, Base):
    __tablename__ = "track_similarity"

    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    similar_track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 0..1, higher = more similar. Computed from ffmpeg-derived features
    # (see app/services/audio_analysis.py).
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint(
            "track_id", "similar_track_id",
            name="uq_track_similarity_pair",
        ),
        Index("ix_track_similarity_track_score", "track_id", "score"),
    )
