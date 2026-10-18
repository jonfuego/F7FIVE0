"""Physical media files. Polymorphic (kind + ref_id) to movie/episode/track/music_video."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class MediaKind(str, enum.Enum):
    movie = "movie"
    episode = "episode"
    track = "track"
    music_video = "music_video"
    podcast_episode = "podcast_episode"


class ScanState(str, enum.Enum):
    pending = "pending"     # probed not yet run
    ready = "ready"         # ffprobe complete, playable
    missing = "missing"     # path no longer exists (soft-delete)
    error = "error"         # probe failed repeatedly


class MediaFile(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "media_files"

    # Polymorphic owner
    kind: Mapped[MediaKind] = mapped_column(
        Enum(MediaKind, name="media_kind"),
        nullable=False,
    )
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # The named library this file belongs to (the library whose folder holds
    # it). Nullable: a file scanned before the backfill, or on an install with no
    # libraries configured, has none and is treated as visible to all. New files
    # always get one at scan/sync time. See app/services/library_access.py.
    library_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("libraries.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Filesystem
    path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    container: Mapped[Optional[str]] = mapped_column(String(32))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Probed stream info
    video_codec: Mapped[Optional[str]] = mapped_column(String(32))
    audio_codec: Mapped[Optional[str]] = mapped_column(String(32))
    audio_channels: Mapped[Optional[int]] = mapped_column(Integer)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    bitrate_kbps: Mapped[Optional[int]] = mapped_column(Integer)

    probed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scan_state: Mapped[ScanState] = mapped_column(
        Enum(ScanState, name="scan_state"),
        default=ScanState.pending,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_media_files_kind_ref", "kind", "ref_id"),
        Index("ix_media_files_scan_state", "scan_state"),
        Index("ix_media_files_library", "library_id"),
        CheckConstraint(
            "(width IS NULL AND height IS NULL) OR (width > 0 AND height > 0)",
            name="ck_media_files_dims_positive",
        ),
    )
