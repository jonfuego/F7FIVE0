"""Path rewriting at the *arr sync boundary.

Radarr and Lidarr report paths on drive letters that are only visible to the
interactive user session that mapped them (e.g. `N:` mapped to a NAS share).
Services running as LocalSystem or any non-interactive account cannot see
those drive letters, so ffprobe and os.path.exists fail and every row ends
up marked `missing`.

Fix: rewrite drive-letter prefixes to the underlying UNC path once, at the
point where the *arr payload hits our DB. Paths are stored canonically as
UNC from then on, which every service account can resolve as long as the
account has credentials to the share (run the services under a user account
that has the share saved in Credential Manager).

Rules come from two places, merged:

  1. Admin > Library folders > Path mappings, saved in the database
     (`app_settings` key `path_mappings`, services/path_mappings.py). These win.
     The API and the stream gateway are separate processes, so each one reloads
     them on a short timer (`_DB_TTL_SEC`); a change reaches both without a
     restart.
  2. `settings.path_rewrite_rules`, a semicolon-delimited string of `SRC=DST`
     pairs from `.env`, read once per process. Example:

         PATH_REWRITE_RULES=N:=\\\\nas\\media

A leading/trailing backslash on either side is normalized away so you can't
double-slash by accident. No rules at all means no rewriting.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

from app.config import settings

log = logging.getLogger("f7five0.path_map")

# `app_settings` key and shape: {"mappings": [{"src": "N:", "dst": "\\\\nas\\share"}]}.
DB_KEY = "path_mappings"
# How long this process trusts the mappings it last read. Short, because a
# second process (the stream gateway) must see an Admin change without a restart.
_DB_TTL_SEC = 3.0


def _parse_rules(raw: str) -> list[tuple[str, str]]:
    """Parse `SRC=DST;SRC=DST` into a list of (src, dst) tuples.

    Both sides are stripped of whitespace and trailing backslashes so that
    `N:` and `N:\\` produce the same rule, and `\\\\host\\share\\` and
    `\\\\host\\share` do too.
    """
    rules: list[tuple[str, str]] = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        src, dst = part.split("=", 1)
        src = src.strip().rstrip("\\")
        dst = dst.strip().rstrip("\\")
        if not src or not dst:
            continue
        rules.append((src, dst))
    return rules


_RULES_CACHE: list[tuple[str, str]] | None = None


def env_rules() -> list[tuple[str, str]]:
    """The `.env` rules. Loaded and cached on first call: settings are frozen at
    process start so a single read is sufficient."""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = _parse_rules(settings.path_rewrite_rules)
    return _RULES_CACHE


_db_lock = threading.Lock()
_db_cache: tuple[float, list[tuple[str, str]]] | None = None


def invalidate() -> None:
    """Forget the cached database mappings, so the next call reads them again.
    Called after Admin saves a change; the other process catches up on its TTL."""
    global _db_cache
    with _db_lock:
        _db_cache = None


def _read_db_rules(db=None) -> list[tuple[str, str]] | None:
    """The saved mappings, or None when they could not be read (no database
    yet, the table missing). Never raises: a path rewrite must not fail a request.

    With a `db` session (the caller's own) the read goes through it. Without
    one this opens a short session of its own, but only on PostgreSQL: the
    SQLite test database shares one connection between sessions, so closing a
    second session there would roll back the caller's open work."""
    try:
        from app.services import app_settings

        if db is not None:
            stored = app_settings.get(db, DB_KEY)
        elif settings.database_url.startswith("postgresql"):
            from app.db import SessionLocal

            own = SessionLocal()
            try:
                stored = app_settings.get(own, DB_KEY)
            finally:
                own.close()
        else:
            return None
    except Exception:
        log.debug("could not read the saved path mappings", exc_info=True)
        return None
    items = (stored or {}).get("mappings") or []
    rules: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        src = str(item.get("src") or "").strip().rstrip("\\")
        dst = str(item.get("dst") or "").strip().rstrip("\\")
        if src and dst:
            rules.append((src, dst))
    # Longest source first, so a deeper mapping wins over a shorter one.
    rules.sort(key=lambda r: len(r[0]), reverse=True)
    return rules


def db_rules(db=None) -> list[tuple[str, str]]:
    """The mappings saved in Admin, reloaded at most every `_DB_TTL_SEC`. Pass
    the caller's `db` when there is one."""
    global _db_cache
    now = time.monotonic()
    with _db_lock:
        cached = _db_cache
        if cached is not None and now - cached[0] < _DB_TTL_SEC:
            return cached[1]
    fresh = _read_db_rules(db)
    with _db_lock:
        if fresh is None:
            # Keep what we had (or nothing) and try again after the TTL.
            fresh = _db_cache[1] if _db_cache is not None else []
        _db_cache = (now, fresh)
        return fresh


def _rules(db=None) -> list[tuple[str, str]]:
    """Every rule in match order: Admin's mappings first, then `.env`."""
    return db_rules(db) + env_rules()


def apply_rule(path: str, src: str, dst: str) -> str | None:
    """`path` rewritten by one rule, or None when the rule does not match.

    Matching is case-insensitive on the source prefix so `N:\\...` and
    `n:\\...` both match. The separator between source and remainder is
    normalized to exactly one backslash so we don't corrupt the path.
    """
    head_len = len(src)
    if len(path) < head_len or path[:head_len].lower() != src.lower():
        return None
    remainder = path[head_len:]
    if remainder.startswith(("\\", "/")):
        remainder = remainder[1:]
    return dst + "\\" + remainder


def translate(path: str | None, db=None) -> str | None:
    """Rewrite `path` according to the saved mappings and the `.env` rules.
    Pass the caller's `db` session when there is one (see _read_db_rules).

    Returns the input unchanged if no rule matches or if rewriting is
    disabled. Returns None for None input so callers can pass-through.
    """
    if not path:
        return path
    for src, dst in _rules(db):
        rewritten = apply_rule(path, src, dst)
        if rewritten is not None:
            return rewritten
    return path


def translate_all(paths: Iterable[str]) -> list[str]:
    """Convenience for batch rewrites (used by the backfill script)."""
    return [translate(p) or p for p in paths]
