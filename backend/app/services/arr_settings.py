"""Radarr, Sonarr and Lidarr settings in use, and the webhook token.

This is the ONE place that reads each app's URL, API key, quality profile id
and root folder, and the shared webhook token. Never read
`settings.radarr_*`, `settings.sonarr_*`, `settings.lidarr_*` or
`settings.arr_webhook_secret` anywhere else: they are only the `.env` defaults
this module falls back to.

Rule (same idea as `tmdb_key`, field by field):

- A value saved from Admin > Arr (app_settings key "arr:<app>", and
  "arr_webhook_secret" for the token) wins over `.env`.
- A saved value that is blank or missing is not a value: that field uses
  `.env`. So a blank box on the Admin page means "keep what is there", never
  "turn it off".
- An admin removes a saved value explicitly: `clear_key` drops the saved API
  key, `clear` drops everything saved for the app, `clear_webhook` drops the
  saved token. After a clear, `.env` applies again (if `.env` has a key, the
  app is still on). `.env` itself is never written.
- A key means the app owns that library (`library_folders.arr_managed`,
  `scan_library`, `/api/client/features`), so every one of those asks here.

The saved values are cached in this process and replaced at once on save or
clear, so nothing needs a restart. The API and its scheduler are one process;
the cache also re-reads the database every minute as a safety net.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.app_setting import AppSetting
from app.services import app_settings

log = logging.getLogger("f7five0.arr_settings")

RADARR = "radarr"
SONARR = "sonarr"
LIDARR = "lidarr"
APPS = (RADARR, SONARR, LIDARR)
# Apps that can take a request: they need a quality profile and a root folder.
REQUEST_APPS = (RADARR, SONARR)

WEBHOOK_KEY = "arr_webhook_secret"
_TTL_SEC = 60.0
_lock = threading.Lock()
_cache: dict = {"data": None, "loaded_at": 0.0}


def _row_key(app: str) -> str:
    return f"arr:{app}"


def _check_app(app: str) -> None:
    if app not in APPS:
        raise ValueError(f"unknown arr app: {app}")


# -- cache ---------------------------------------------------------------
def _load_all() -> dict[str, dict]:
    from sqlalchemy import select

    from app.db import db_session
    keys = [_row_key(a) for a in APPS] + [WEBHOOK_KEY]
    try:
        with db_session() as db:
            rows = db.scalars(select(AppSetting).where(AppSetting.key.in_(keys))).all()
            return {r.key: dict(r.value) for r in rows if isinstance(r.value, dict)}
    except Exception:
        log.warning("could not read the saved *arr settings; using .env", exc_info=True)
        return {}


def _data() -> dict[str, dict]:
    with _lock:
        fresh = time.monotonic() - _cache["loaded_at"] < _TTL_SEC
        if fresh and _cache["data"] is not None:
            return _cache["data"]
    data = _load_all()
    with _lock:
        _cache.update(data=data, loaded_at=time.monotonic())
    return data


def _set_row(key: str, value: Optional[dict]) -> None:
    """Save-time refresh: the new value is live in this process at once."""
    data = dict(_data())
    if value:
        data[key] = dict(value)
    else:
        data.pop(key, None)
    with _lock:
        _cache.update(data=data, loaded_at=time.monotonic())


def reset_cache() -> None:
    """Tests: forget the cached values."""
    with _lock:
        _cache.update(data=None, loaded_at=0.0)


def _saved_row(app: str, db: Optional[Session]) -> dict:
    if db is not None:
        return app_settings.get(db, _row_key(app)) or {}
    return _data().get(_row_key(app)) or {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _saved_int(value: object) -> int:
    try:
        n = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


# -- reads (what the rest of the app uses) ---------------------------------
def url(app: str, db: Optional[Session] = None) -> str:
    """The base URL to call, without a trailing slash."""
    _check_app(app)
    saved = _text(_saved_row(app, db).get("url"))
    return (saved or _text(getattr(settings, f"{app}_url"))).rstrip("/")


def api_key(app: str, db: Optional[Session] = None) -> str:
    """The API key in use ("" = this app is off)."""
    _check_app(app)
    return _text(_saved_row(app, db).get("api_key")) or _text(getattr(settings, f"{app}_api_key"))


def creds(app: str) -> tuple[str, str]:
    """(url, api_key) for `RadarrClient(*creds("radarr"))`."""
    return url(app), api_key(app)


def configured(app: str) -> bool:
    """True when this app has a key: it owns its library, and Requests can use it."""
    return bool(api_key(app))


def quality_profile_id(app: str, db: Optional[Session] = None) -> int:
    """The profile approved requests are added with (0 = not chosen yet)."""
    if app not in REQUEST_APPS:
        raise ValueError(f"{app} has no request settings")
    return _saved_int(_saved_row(app, db).get("quality_profile_id")) or _saved_int(
        getattr(settings, f"{app}_quality_profile_id"))


def root_folder(app: str, db: Optional[Session] = None) -> str:
    """The root folder approved requests are added to ("" = not chosen yet)."""
    if app not in REQUEST_APPS:
        raise ValueError(f"{app} has no request settings")
    return _text(_saved_row(app, db).get("root_folder")) or _text(getattr(settings, f"{app}_root_folder"))


def webhook_secret(db: Optional[Session] = None) -> str:
    """The token the *arr webhooks must present ("" = webhooks are refused)."""
    if db is not None:
        saved = _text((app_settings.get(db, WEBHOOK_KEY) or {}).get("value"))
    else:
        saved = _text((_data().get(WEBHOOK_KEY) or {}).get("value"))
    return saved or _text(settings.arr_webhook_secret)


# -- where each value comes from (for the Admin page) -----------------------
def key_source(db: Session, app: str) -> Optional[str]:
    """"admin" (saved here), "env" (.env) or None (no key)."""
    _check_app(app)
    if _text(_saved_row(app, db).get("api_key")):
        return "admin"
    if _text(getattr(settings, f"{app}_api_key")):
        return "env"
    return None


def url_source(db: Session, app: str) -> str:
    _check_app(app)
    return "admin" if _text(_saved_row(app, db).get("url")) else "env"


def field_source(db: Session, app: str, field: str) -> Optional[str]:
    """"admin" / "env" / None for quality_profile_id and root_folder."""
    if app not in REQUEST_APPS:
        raise ValueError(f"{app} has no request settings")
    if field == "quality_profile_id":
        if _saved_int(_saved_row(app, db).get(field)):
            return "admin"
        return "env" if _saved_int(getattr(settings, f"{app}_quality_profile_id")) else None
    if _text(_saved_row(app, db).get(field)):
        return "admin"
    return "env" if _text(getattr(settings, f"{app}_{field}")) else None


def webhook_source(db: Session) -> Optional[str]:
    if _text((app_settings.get(db, WEBHOOK_KEY) or {}).get("value")):
        return "admin"
    return "env" if _text(settings.arr_webhook_secret) else None


def masked(key: str) -> str:
    """Six dots and the last four characters; never the whole key."""
    key = key.strip()
    return ("•" * 6 + key[-4:]) if len(key) > 4 else ("•" * len(key))


# -- writes -----------------------------------------------------------------
def save(
    db: Session,
    app: str,
    *,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    quality_profile_id: Optional[int] = None,
    root_folder: Optional[str] = None,
) -> None:
    """Partial update of what is saved for `app`. For each field: None leaves it
    alone; "" (or 0 for the profile) removes the saved value so `.env` applies
    again, except `api_key`, where "" also leaves it alone (the key box is
    write-only and stays blank) and `clear_key` removes it. The caller commits."""
    _check_app(app)
    row = dict(app_settings.get(db, _row_key(app)) or {})
    if url is not None:
        _put_or_drop(row, "url", url.strip().rstrip("/"))
    if api_key is not None and api_key.strip():
        row["api_key"] = api_key.strip()
    if quality_profile_id is not None:
        if app not in REQUEST_APPS:
            raise ValueError(f"{app} has no request settings")
        _put_or_drop(row, "quality_profile_id", quality_profile_id if quality_profile_id > 0 else None)
    if root_folder is not None:
        if app not in REQUEST_APPS:
            raise ValueError(f"{app} has no request settings")
        _put_or_drop(row, "root_folder", root_folder.strip())
    _store(db, app, row)


def clear_key(db: Session, app: str) -> None:
    """Remove the saved API key. `.env` applies again if it has one."""
    _check_app(app)
    row = dict(app_settings.get(db, _row_key(app)) or {})
    row.pop("api_key", None)
    _store(db, app, row)


def clear(db: Session, app: str) -> None:
    """Remove everything saved for the app (key, URL, profile, root folder)."""
    _check_app(app)
    _store(db, app, {})


def _put_or_drop(row: dict, field: str, value: object) -> None:
    if value in (None, "", 0):
        row.pop(field, None)
    else:
        row[field] = value


def _store(db: Session, app: str, row: dict) -> None:
    key = _row_key(app)
    if row:
        app_settings.put(db, key, row)
    else:
        app_settings.delete(db, key)
    _set_row(key, row)


def new_webhook_secret() -> str:
    """A fresh token: 43 URL-safe characters (256 bits)."""
    return secrets.token_urlsafe(32)


def save_webhook_secret(db: Session, token: str) -> None:
    token = token.strip()
    app_settings.put(db, WEBHOOK_KEY, {"value": token})
    _set_row(WEBHOOK_KEY, {"value": token})


def clear_webhook_secret(db: Session) -> None:
    app_settings.delete(db, WEBHOOK_KEY)
    _set_row(WEBHOOK_KEY, None)
