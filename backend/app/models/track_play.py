"""Per-user audio play log.

One row per finished or skipped-with-progress track. Powers the
Most Played / Never Played / Recently Played / Artist Radio kinds in
the auto-playlist module. Sized to be cheap: no indexes beyond the two
the playlist queries need.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import UUIDPKMixin


class TrackPlay(UUIDPKMixin, Base):
    __tablename__ = "track_plays"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        nullable=False,
    )
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ms_played: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_track_plays_user_track", "user_id", "track_id"),
        Index("ix_track_plays_user_at_desc", "user_id", "played_at"),
    )
