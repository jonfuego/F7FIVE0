"""Transcode session records and HLS segment cache index."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class TranscodeSession(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "transcode_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False)  # "high", "medium", "low", "original"
    # Resume offset in seconds, quantized to OFFSET_BUCKET_SEC. 0 means
    # playback started at the beginning. A nonzero value means the user
    # resumed mid-file; ffmpeg was spawned with input-side `-ss <bucket>`
    # so segments start at PTS 0 representing source content from the
    # bucket onward. The client seeks to the bucket after metadata loads
    # so the player timer reads the real source time.
    offset_bucket: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    direct_play: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bytes_served: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Latest ffmpeg realtime factor (encoded media time / wall time), parsed
    # from `-progress` by the stream gateway and written here so the admin API
    # (a separate process) can read it. Null for direct-play and until the
    # first progress block arrives. `below_realtime_sec` is how long the encode
    # has stayed under 1.0x; the admin flags "server can't keep up" past 30s.
    speed: Mapped[Optional[float]] = mapped_column(Float)
    below_realtime_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TranscodeCache(UUIDPKMixin, TimestampMixin, Base):
    """Tracks on-disk HLS output per (media_file, variant, offset_bucket).

    LRU eviction reads this to decide which entry to delete next. The
    offset_bucket column keeps sister rows distinct when a single file
    has multiple concurrent transcodes starting from different offsets.
    """

    __tablename__ = "transcode_cache"

    media_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False)
    offset_bucket: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    segment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_access_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "media_file_id", "variant", "offset_bucket",
            name="uq_transcode_cache_file_variant_bucket",
        ),
        Index("ix_transcode_cache_last_access", "last_access_at"),
    )
