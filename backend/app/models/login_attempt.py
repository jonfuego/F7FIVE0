"""Durable login-attempt records for the login throttle (SEC-P1-4).

One row per failed or blocked login attempt. The throttle counts these over a
sliding window instead of the old in-process dict, so the limits survive a
restart and would coordinate across workers. Rows age out of the window and a
successful login clears the account's rows for that IP, so the table stays
small. See app/services/login_throttle.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import UUIDPKMixin


class LoginAttempt(UUIDPKMixin, Base):
    __tablename__ = "login_attempts"

    # The attempted username, lower-cased (recorded whether or not the user
    # exists, so the throttle doesn't become a username oracle).
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # The real client IP from app/services/trusted_proxy.py (SEC-P1-1). Null
    # when it could not be determined; per-IP limits then don't apply.
    client_ip: Mapped[Optional[str]] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_login_attempts_username_at", "username", "at"),
        Index("ix_login_attempts_ip_at", "client_ip", "at"),
    )
