"""Which library a Radarr / Sonarr / Lidarr root folder maps to.

Each *arr app owns one kind of library (Radarr -> movies, Sonarr -> TV, Lidarr
-> music), but a kind can now have more than one library. This records, per app,
a map of root-folder path -> library id, so the sync can stamp each file with
the right library. With no explicit mapping for a path, it falls back to the
first library of the app's kind.

Stored in `app_settings` under the key `arr_library_map`:

    {"radarr": {"<root path lower>": "<library id>"}, "sonarr": {...}, ...}

Only access/name/sort of a library matter in phase 1; this is the one phase-1
writer of per-library *arr configuration.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import Library, LibraryKind
from app.services import app_settings

KEY = "arr_library_map"

# Radarr owns movies, Sonarr owns TV, Lidarr owns music.
APP_KIND = {
    "radarr": "movies",
    "sonarr": "tv",
    "lidarr": "music",
}


def _norm(path: str) -> str:
    return (path or "").replace("/", "\\").rstrip("\\").lower()


def _read(db: Session) -> dict:
    return app_settings.get(db, KEY) or {}


def get_map(db: Session, app: str) -> dict[str, str]:
    """The saved {root path (lowercased) -> library id string} map for an app."""
    stored = _read(db)
    app_map = stored.get(app)
    return dict(app_map) if isinstance(app_map, dict) else {}


def default_library_id(db: Session, app: str) -> Optional[uuid.UUID]:
    """The first library of the app's kind (lowest sort_order), or None."""
    kind = APP_KIND.get(app)
    if kind is None:
        return None
    lib = db.scalars(
        select(Library).where(Library.kind == LibraryKind(kind))
        .order_by(Library.sort_order, Library.created_at)
    ).first()
    return lib.id if lib is not None else None


def set_root_library(db: Session, app: str, root_path: str, library_id: uuid.UUID) -> None:
    """Map one *arr root folder to a library. The caller commits."""
    if app not in APP_KIND:
        raise ValueError(f"unknown app: {app}")
    stored = _read(db)
    app_map = dict(stored.get(app) or {})
    app_map[_norm(root_path)] = str(library_id)
    stored[app] = app_map
    app_settings.put(db, KEY, stored)


def clear_root(db: Session, app: str, root_path: str) -> None:
    """Drop the mapping for one root so it falls back to the default. Caller commits."""
    stored = _read(db)
    app_map = dict(stored.get(app) or {})
    app_map.pop(_norm(root_path), None)
    stored[app] = app_map
    app_settings.put(db, KEY, stored)


def library_for(db: Session, app: str, path: str) -> Optional[uuid.UUID]:
    """The library id a file at `path` (reported by this app) belongs to.

    Uses the longest root in the app's map that is a prefix of `path`; falls
    back to the first library of the app's kind. Returns None only when the kind
    has no library at all."""
    app_map = get_map(db, app)
    if app_map and path:
        target = _norm(path)
        best_id: Optional[str] = None
        best_len = -1
        for root, lib_id in app_map.items():
            if target == root or target.startswith(root + "\\"):
                if len(root) > best_len:
                    best_id, best_len = lib_id, len(root)
        if best_id is not None:
            try:
                return uuid.UUID(str(best_id))
            except (ValueError, TypeError):
                pass
    return default_library_id(db, app)
