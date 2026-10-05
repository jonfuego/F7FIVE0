"""Admin reminders shown as a banner in the web app.

Each reminder has a condition. While it holds, admins see the banner until
they snooze it; it comes back after SNOOZE_DAYS and stops for good after
MAX_SHOWINGS snoozes (or "Don't remind me again"). State is per admin, in
app_settings ("reminder:<id>:<user id>"), so it follows them across devices.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.services import app_settings, tmdb_key

SNOOZE_DAYS = 3
MAX_SHOWINGS = 3


@dataclass(frozen=True)
class Reminder:
    id: str
    title: str
    body: str
    action_label: str
    action_href: str
    applies: Callable[[Session], bool]


REMINDERS: tuple[Reminder, ...] = (
    Reminder(
        id="tmdb_key",
        title="Add a TMDB key for posters and descriptions",
        body=(
            "Movies and shows found in your folders get their posters, backdrops, "
            "and descriptions from TMDB. The key is free and takes a couple of minutes."
        ),
        action_label="Add key",
        action_href="/admin#metadata",
        applies=lambda db: not tmdb_key.get(),
    ),
)
_BY_ID = {r.id: r for r in REMINDERS}


def _key(reminder_id: str, user_id: uuid.UUID) -> str:
    return f"reminder:{reminder_id}:{user_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def active(db: Session, user_id: uuid.UUID) -> list[Reminder]:
    out: list[Reminder] = []
    for r in REMINDERS:
        if not r.applies(db):
            continue
        state = app_settings.get(db, _key(r.id, user_id)) or {}
        if int(state.get("count") or 0) >= MAX_SHOWINGS:
            continue
        until = state.get("snoozed_until")
        if until:
            try:
                if datetime.fromisoformat(until) > _now():
                    continue
            except ValueError:
                pass
        out.append(r)
    return out


def snooze(db: Session, user_id: uuid.UUID, reminder_id: str, *, forever: bool = False) -> None:
    if reminder_id not in _BY_ID:
        raise KeyError(reminder_id)
    state = app_settings.get(db, _key(reminder_id, user_id)) or {}
    count = MAX_SHOWINGS if forever else int(state.get("count") or 0) + 1
    app_settings.put(db, _key(reminder_id, user_id), {
        "count": count,
        "snoozed_until": (_now() + timedelta(days=SNOOZE_DAYS)).isoformat(),
    })
