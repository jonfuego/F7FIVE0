"""WebAuthn passkeys: stored credentials and single-use ceremony challenges.

Two tables, both additive (migration 0022):

- `webauthn_credentials`: one row per registered passkey. Holds the credential
  id and COSE public key (both base64url text), the running signature counter
  used to detect cloned authenticators, the reported transports and AAGUID, a
  user-editable name, and usage timestamps.
- `webauthn_challenges`: one row per issued register/login challenge. Challenges
  live in the DB (not process memory) so the stateless, single-worker API can
  verify a ceremony it started, and so a challenge is provably single-use across
  restarts. `user_id` is null for login challenges (discoverable credentials
  resolve the user from the assertion's user handle).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._mixins import UUIDPKMixin


class WebAuthnCredential(UUIDPKMixin, Base):
    """A registered passkey belonging to one user."""

    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # base64url-encoded credential id (the authenticator's handle). Unique so a
    # login assertion can resolve exactly one stored credential.
    credential_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    # base64url-encoded COSE public key used to verify assertions.
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Running signature counter. A login whose reported counter regresses below
    # this (when the stored value is non-zero) is rejected as a possible clone.
    sign_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # Comma-joined transports (e.g. "internal,hybrid"), null if unreported.
    transports: Mapped[Optional[str]] = mapped_column(String(128))
    aaguid: Mapped[Optional[str]] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Passkey")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user = relationship("User")

    __table_args__ = (
        Index("ix_webauthn_credentials_user", "user_id"),
    )


class WebAuthnChallenge(UUIDPKMixin, Base):
    """A single-use register/login challenge, verified once then consumed."""

    __tablename__ = "webauthn_challenges"

    # base64url-encoded challenge value, matched against the assertion's
    # clientDataJSON.challenge on verify.
    challenge: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Null for login challenges (discoverable credentials); set for register.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "register" | "login"
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_webauthn_challenges_lookup", "challenge", "kind"),
    )
