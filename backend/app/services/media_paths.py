"""One place that decides whether a media file path may be read.

The stream gateway, the API download/subtitle/stream-start/lyrics routes, audio
analysis and the *arr sync all read paths that come out of the database (or out
of Radarr, Sonarr and Lidarr). Every one of them goes through this module before
it opens, probes, extracts or serves a byte, so a poisoned row or a hostile
*arr payload cannot point the service account at a file outside the library
folders (SEC-P0-4).

`allowed_roots` is what the gateway has always used: the active library-folder
configuration plus `STREAM_ALLOWED_ROOTS`, each in raw and path-mapped form.
With nothing configured every path is refused. The only bypass is
`STREAM_UNSAFE_ALLOW_ANY_PATH`, off by default and for local development.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.services import library_folders
from app.services.path_map import translate as translate_path
from app.services.range_response import ensure_under_roots

log = logging.getLogger("f7five0.media_paths")


def allowed_roots(db: Session) -> list[Path]:
    """Every directory a media file is allowed to live under.

    Derived from the active library-folder configuration (the `libraries`
    table once Admin saves folders, else the `LIBRARY_ROOT_*` env keys), plus
    any explicit `STREAM_ALLOWED_ROOTS` entries. Each configured folder is
    added in both its raw form and its path-rewritten form (drive letter ->
    UNC) so a root matches whichever shape `media_files.path` was stored in.
    Returns an empty list only when nothing is configured; callers fail closed
    on that.
    """
    roots: list[Path] = []

    def _add(p: str) -> None:
        p = (p or "").strip()
        if not p:
            return
        roots.append(Path(p))
        translated = translate_path(p, db)
        if translated and translated != p:
            roots.append(Path(translated))

    for paths in library_folders.all_folders(db).values():
        for p in paths:
            _add(p)
    for p in (settings.stream_allowed_roots or "").split(";"):
        _add(p)
    return roots


def contain(db: Session, path: Path) -> Path:
    """Enforce root containment, or bypass it only under the explicit,
    off-by-default unsafe development flag. With the flag off and no roots
    configured, every file is rejected (SEC-P0-4 fail closed). Raises
    HTTP 403 `path_outside_library_roots`."""
    if settings.stream_unsafe_allow_any_path:
        log.warning(
            "stream_unsafe_allow_any_path is ON: serving %s without root "
            "containment. Never use this on a reachable install.", path,
        )
        return path.resolve(strict=False)
    return ensure_under_roots(path, allowed_roots(db))


def resolve_contained_media_path(db: Session, mf_or_path: Union[str, Path, object]) -> Path:
    """Translate a stored media path (drive letter -> UNC) and require it to sit
    under the library roots. Takes a `MediaFile` or a plain path. Returns the
    resolved path to read, or raises HTTP 403 `path_outside_library_roots`.

    Call this before every probe, extract, transcode or byte response outside
    the stream gateway. Never read `path_map.translate(mf.path)` directly.
    """
    raw = mf_or_path if isinstance(mf_or_path, (str, Path)) else mf_or_path.path
    raw = str(raw)
    return contain(db, Path(translate_path(raw, db) or raw))


def is_contained(db: Session, path: str) -> bool:
    """True when `path` (translated) is under the library roots. Never raises;
    for ingestion code that skips a bad path instead of failing a request."""
    try:
        resolve_contained_media_path(db, path)
    except HTTPException:
        return False
    return True
