"""The TMDB API key in use.

A key saved in Admin > Metadata (app_settings "tmdb_api_key") wins over
TMDB_API_KEY in `.env`. Callers that run deep in scans and enrichment have
no session, so the saved value is cached in-process and refreshed every
minute; saving or removing a key refreshes it at once. The API, its
scheduler, and every TMDB caller live in the one API process.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.services import app_settings

log = logging.getLogger("f7five0.tmdb_key")

SETTING_KEY = "tmdb_api_key"
_TTL_SEC = 60.0
_lock = threading.Lock()
_cache: dict = {"value": None, "loaded_at": 0.0}


def _load_saved() -> str:
    from app.db import db_session
    try:
        with db_session() as db:
            row = app_settings.get(db, SETTING_KEY)
    except Exception:
        log.warning("could not read the saved TMDB key; using .env", exc_info=True)
        return ""
    return str((row or {}).get("value") or "").strip()


def saved(db: Optional[Session] = None) -> str:
    """The key saved from the Admin page, or ""."""
    if db is not None:
        return str((app_settings.get(db, SETTING_KEY) or {}).get("value") or "").strip()
    with _lock:
        fresh = time.monotonic() - _cache["loaded_at"] < _TTL_SEC
        if fresh and _cache["value"] is not None:
            return _cache["value"]
    value = _load_saved()
    with _lock:
        _cache.update(value=value, loaded_at=time.monotonic())
    return value


def get() -> str:
    """The key every TMDB caller should use ("" = TMDB is off)."""
    return saved() or (settings.tmdb_api_key or "").strip()


def source(db: Session) -> Optional[str]:
    if saved(db):
        return "admin"
    if (settings.tmdb_api_key or "").strip():
        return "env"
    return None


def masked(key: str) -> str:
    key = key.strip()
    return ("•" * 6 + key[-4:]) if len(key) > 4 else ("•" * len(key))


def save(db: Session, key: str) -> None:
    app_settings.put(db, SETTING_KEY, {"value": key.strip()})
    _set_cache(key.strip())


def clear(db: Session) -> None:
    app_settings.delete(db, SETTING_KEY)
    _set_cache("")


def _set_cache(value: str) -> None:
    with _lock:
        _cache.update(value=value, loaded_at=time.monotonic())


def reset_cache() -> None:
    """Tests: forget the cached value."""
    with _lock:
        _cache.update(value=None, loaded_at=0.0)


class KeyCheck:
    def __init__(self, ok: bool, message: str) -> None:
        self.ok, self.message = ok, message


def check(key: str, client: Optional[httpx.Client] = None) -> KeyCheck:
    """Ask TMDB whether `key` works (a v3 API key, the 32-character one)."""
    key = (key or "").strip()
    if not key:
        return KeyCheck(False, "Paste your TMDB API key first.")
    if key.startswith("eyJ"):
        return KeyCheck(False, "That looks like the long 'API Read Access Token'. Use the shorter 'API Key' from the same TMDB page.")
    own = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        resp = client.get("https://api.themoviedb.org/3/configuration", params={"api_key": key})
    except httpx.HTTPError as exc:
        return KeyCheck(False, f"Could not reach TMDB from the server: {exc.__class__.__name__}. Check its internet connection.")
    finally:
        if own:
            client.close()
    if resp.status_code == 200:
        return KeyCheck(True, "TMDB accepted the key.")
    if resp.status_code in (401, 403):
        return KeyCheck(False, "TMDB rejected that key. Copy the 'API Key' from themoviedb.org > Settings > API.")
    return KeyCheck(False, f"TMDB answered {resp.status_code}. Try again in a minute.")
