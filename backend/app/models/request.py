"""User media requests (Overseerr-style ask -> approve -> available flow)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import UUIDPKMixin


# kind values
KIND_MOVIE = "movie"
KIND_SERIES = "series"
REQUEST_KINDS = frozenset({KIND_MOVIE, KIND_SERIES})

# status lifecycle: pending -> approved -> available, or pending -> denied
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_AVAILABLE = "available"


class Request(UUIDPKMixin, Base):
    """One user's ask for a movie or series.

    `external_id` is the TMDB id for movies and the TVDB id for series
    (stored as a string so both id spaces share one column). The partial
    unique index in migration 0018 keeps one open (non-denied) request per
    (kind, external_id). resolved_at stamps when the request reaches a
    terminal-ish state: denied, or available once the item syncs in.
    """

    __tablename__ = "requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    poster_url: Mapped[Optional[str]] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING,
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_requests_user_id", "user_id"),
        Index("ix_requests_status", "status"),
    )
