"""Read/write helpers for the app_settings table."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting


def get(db: Session, key: str) -> Optional[dict]:
    row = db.get(AppSetting, key)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else None


def put(db: Session, key: str, value: dict) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=dict(value)))
    else:
        row.value = dict(value)
    db.flush()


def delete(db: Session, key: str) -> None:
    row = db.get(AppSetting, key)
    if row is not None:
        db.delete(row)
        db.flush()
