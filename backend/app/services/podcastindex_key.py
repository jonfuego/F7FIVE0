"""The Podcast Index key and secret in use.

Podcast Index (podcastindex.org) is the directory behind podcast search when
the admin has registered for a key. It is optional: with no key, search falls
back to Apple's iTunes Search API, which needs none.

Works like `tmdb_key`: a pair saved in Admin > Metadata (app_settings
`podcastindex_api`, `{key, secret}`) wins over PODCASTINDEX_API_KEY and
PODCASTINDEX_API_SECRET in `.env`. Callers deep in a search request have no
session, so the saved value is cached in-process and refreshed every minute;
saving or removing the pair refreshes it at once. Both halves must be present:
a key without its secret is no key.

The secret is never returned by the API, never logged, and never part of an
exception message; only `secret_set` leaves this module.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.services import app_settings

log = logging.getLogger("f7five0.podcastindex_key")

SETTING_KEY = "podcastindex_api"
_TTL_SEC = 60.0
_lock = threading.Lock()
_cache: dict = {"value": None, "loaded_at": 0.0}

Credentials = tuple[str, str]
NONE: Credentials = ("", "")


def _clean(row: Optional[dict]) -> Credentials:
    key = str((row or {}).get("key") or "").strip()
    secret = str((row or {}).get("secret") or "").strip()
    return (key, secret) if key and secret else NONE


def _load_saved() -> Credentials:
    from app.db import db_session
    try:
        with db_session() as db:
            return _clean(app_settings.get(db, SETTING_KEY))
    except Exception:
        log.warning("could not read the saved Podcast Index key; using .env", exc_info=False)
        return NONE


def saved(db: Optional[Session] = None) -> Credentials:
    """The pair saved from the Admin page, or ("", "")."""
    if db is not None:
        return _clean(app_settings.get(db, SETTING_KEY))
    with _lock:
        fresh = time.monotonic() - _cache["loaded_at"] < _TTL_SEC
        if fresh and _cache["value"] is not None:
            return _cache["value"]
    value = _load_saved()
    with _lock:
        _cache.update(value=value, loaded_at=time.monotonic())
    return value


def env() -> Credentials:
    key = (settings.podcastindex_api_key or "").strip()
    secret = (settings.podcastindex_api_secret or "").strip()
    return (key, secret) if key and secret else NONE


def get() -> Credentials:
    """(key, secret) every Podcast Index caller should use; ("", "") = not set."""
    return saved() if saved() != NONE else env()


def configured() -> bool:
    return get() != NONE


def source(db: Session) -> Optional[str]:
    if saved(db) != NONE:
        return "admin"
    if env() != NONE:
        return "env"
    return None


def effective(db: Session) -> Credentials:
    return saved(db) if saved(db) != NONE else env()


def masked(key: str) -> str:
    key = key.strip()
    return ("•" * 6 + key[-4:]) if len(key) > 4 else ("•" * len(key))


def save(db: Session, key: str, secret: str) -> None:
    app_settings.put(db, SETTING_KEY, {"key": key.strip(), "secret": secret.strip()})
    _set_cache(_clean({"key": key, "secret": secret}))


def clear(db: Session) -> None:
    app_settings.delete(db, SETTING_KEY)
    _set_cache(NONE)


def _set_cache(value: Credentials) -> None:
    with _lock:
        _cache.update(value=value, loaded_at=time.monotonic())


def reset_cache() -> None:
    """Tests: forget the cached value."""
    with _lock:
        _cache.update(value=None, loaded_at=0.0)
