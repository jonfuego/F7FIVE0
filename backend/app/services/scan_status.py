"""State of the library folder scan, for Admin and the empty library pages.

Kept in `app_settings` under `folder_scan_status` so every process and the
web app read the same thing:

    {state: "idle" | "running", started_at, finished_at, current_library,
     libraries: {movies | tv | music: {state, seen, added, probed, missing,
                                       errors}},
     last_error}

A library's `state` is queued, running, done, or failed. The scan writes this
at the start, at every batch commit, and at the end. Nothing here commits:
the caller does (the scan commits the status together with the rows it just
saved, so what Admin shows is never ahead of what the library holds).

If the API process dies mid-scan, `running` would stay forever. API startup
calls `reset_stale`, which turns it into `idle` with a `last_error` that says
the last scan was interrupted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.services import app_settings

KEY = "folder_scan_status"

INTERRUPTED = "The last scan was interrupted (the server stopped before it finished)."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blank() -> dict:
    return {
        "state": "idle", "started_at": None, "finished_at": None,
        "current_library": None, "libraries": {}, "last_error": None,
    }


def read(db: Session) -> dict:
    """The stored status, with every field present."""
    out = _blank()
    stored = app_settings.get(db, KEY)
    if stored:
        out.update({k: v for k, v in stored.items() if k in out})
        if not isinstance(out["libraries"], dict):
            out["libraries"] = {}
    return out


def is_running(db: Session) -> bool:
    return read(db)["state"] == "running"


def begin(db: Session, *, force: bool = False) -> bool:
    """Mark a scan as running. False (and nothing changes) when one is already
    marked running, unless `force` (the scan job itself, which restarts the
    record it was queued under)."""
    current = read(db)
    if current["state"] == "running" and not force:
        return False
    app_settings.put(db, KEY, {
        "state": "running", "started_at": _now(),
        # The last finished time stays until this scan finishes.
        "finished_at": current["finished_at"],
        "current_library": None, "libraries": {}, "last_error": None,
    })
    return True


def _counts(label: str, state: str, stats) -> dict:
    added = {"movies": "movies", "tv": "episodes", "music": "tracks"}[label]
    return {
        "state": state,
        "seen": stats.files_seen,
        "added": getattr(stats, added),
        "probed": stats.files_probed,
        "missing": stats.files_missing,
        "errors": stats.errors,
    }


def set_library(db: Session, label: str, state: str, stats, error: Optional[str] = None) -> None:
    """Record one library's state and counts. `error` also becomes `last_error`."""
    current = read(db)
    current["libraries"][label] = _counts(label, state, stats)
    if state == "running":
        current["current_library"] = label
    elif current["current_library"] == label:
        current["current_library"] = None
    if error:
        current["last_error"] = error
    app_settings.put(db, KEY, current)


def finish(db: Session, error: Optional[str] = None) -> None:
    """The scan is over. A library failure recorded earlier stays as `last_error`."""
    current = read(db)
    current["state"] = "idle"
    current["finished_at"] = _now()
    current["current_library"] = None
    if error:
        current["last_error"] = error
    app_settings.put(db, KEY, current)


def reset_stale(db: Session) -> bool:
    """On API start: a `running` record belongs to a process that is gone."""
    current = read(db)
    if current["state"] != "running":
        return False
    current["state"] = "idle"
    current["current_library"] = None
    current["last_error"] = INTERRUPTED
    for lib in current["libraries"].values():
        if isinstance(lib, dict) and lib.get("state") in ("queued", "running"):
            lib["state"] = "interrupted"
    app_settings.put(db, KEY, current)
    return True


def scan_state(db: Session) -> dict:
    """What every signed-in user may see: whether a scan is running, and when
    the last one finished."""
    current = read(db)
    return {"running": current["state"] == "running", "finished_at": current["finished_at"]}
