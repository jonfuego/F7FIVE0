"""Saved library views, per user, on the server.

One row per (user, view key): which Music browse tab, the movie genre and
sort, the TV filter, and so on. Stored here instead of in the browser or on
the phone so a view follows the person across web, phone and TV. Keys look
like `music.browse` or `sort:movies`; the value is small JSON.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserViewPref(Base):
    __tablename__ = "user_view_prefs"

    # The primary key (user_id, view_key) is the unique constraint on
    # user + key.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    view_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
