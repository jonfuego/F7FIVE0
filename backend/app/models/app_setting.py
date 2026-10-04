"""Small server settings changed from the Admin page (key/value).

For values that must change without editing `.env` or restarting, and that
the API may need to write while running as a non-admin service account
(it can only read `.env`). Values are JSON. Keys in use:

- "tmdb_api_key": {"value": "<key>"} (app/services/tmdb_key.py)
- "reminder:<name>:<user id>": {"snoozed_until": iso, "count": n}
  (app/services/reminders.py)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
