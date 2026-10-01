"""Users, sessions (refresh tokens), and auth audit events."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Boolean
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class UserRole(str, enum.Enum):
    admin = "admin"
    member = "member"
    # Synthetic role for the seeded system user that owns sync-originated
    # art_overrides rows. is_active=False keeps it unauthenticated; the
    # 0017 migration adds the value to the Postgres user_role enum.
    system = "system"


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.member,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # When the user last loaded the home page. Drives the new-arrivals badge:
    # items added after this stamp count as "new since your last visit".
    # Null until the first /recent/seen stamp (treated as account creation).
    last_seen_home_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Session(UUIDPKMixin, TimestampMixin, Base):
    """One row per issued refresh token. Rotated on every refresh."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    device_label: Mapped[Optional[str]] = mapped_column(String(120))
    client_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="browser",
    )
    # Device metadata reported by native clients at login. Null for browser
    # and pre-2.0 rows. `platform` is e.g. "android" / "ios" / "android_tv";
    # `client_version` is the app's semver string used by the min-version gate.
    platform: Mapped[Optional[str]] = mapped_column(String(32))
    client_version: Mapped[Optional[str]] = mapped_column(String(32))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Refresh-rotation grace window. When a session is rotated, `rotated_at`
    # is stamped (alongside revoked_at). The immediately-previous token is
    # then accepted exactly once within ROTATION_GRACE_SECONDS to survive a
    # refresh response lost to a network drop or app suspension; `grace_used`
    # flips true the moment that one grace acceptance happens. A session
    # revoked by logout / password change / admin action leaves rotated_at
    # null, so it is never grace-eligible.
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    grace_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_active", "user_id", "revoked_at"),
        Index("ix_sessions_client_type", "client_type"),
    )


class AuthEvent(UUIDPKMixin, Base):
    """Auth audit log: login success/fail, logout, refresh, admin actions."""

    __tablename__ = "auth_events"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_auth_events_user_at", "user_id", "at"),
    )
