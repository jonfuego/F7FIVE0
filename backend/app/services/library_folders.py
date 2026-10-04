r"""Library source folders: one or more per library.

Where the folders come from:

- The `libraries` table, one row per folder (kind + root_path). Admin >
  Library folders writes it. Once the table has any row it is the only
  source, for every library: a library with no rows is not configured.
- Otherwise the `.env` keys LIBRARY_ROOT_MOVIES / _TV / _MUSIC /
  _MUSIC_VIDEOS. Each takes one folder or several separated by `;`
  (Setup writes them this way).

Folders keep the order they were given in. Paths are stored as typed;
`translate()` from path_map is applied where media_files paths are compared.
"""
from __future__ import annotations

import ntpath
import os
import posixpath
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.library import Library, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services.path_map import translate as translate_path

KINDS: tuple[str, ...] = ("movies", "tv", "music", "music_videos")
LABELS = {"movies": "Movies", "tv": "TV shows", "music": "Music", "music_videos": "Music videos"}
MAX_FOLDERS_PER_LIBRARY = 20


def parse(raw: Optional[str]) -> list[str]:
    r"""`D:\Movies; \\nas\Movies` -> ["D:\Movies", "\\nas\Movies"]. Blank
    entries are dropped, duplicates (case-insensitive) keep the first."""
    out: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").replace("\r", "\n").replace("\n", ";").split(";"):
        p = part.strip().strip('"').strip()
        if not p:
            continue
        key = _key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _key(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").lower()


def env_folders(kind: str) -> list[str]:
    return parse(getattr(settings, f"library_root_{kind}", ""))


def db_managed(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Library)))


def folders(db: Optional[Session], kind: str) -> list[str]:
    """Effective folders for one library."""
    if db is not None and db_managed(db):
        rows = db.scalars(
            select(Library).where(Library.kind == LibraryKind(kind)).order_by(Library.created_at, Library.root_path)
        ).all()
        return [r.root_path for r in rows]
    return env_folders(kind)


def all_folders(db: Optional[Session]) -> dict[str, list[str]]:
    return {k: folders(db, k) for k in KINDS}


def source(db: Session) -> str:
    return "admin" if db_managed(db) else "env"


# ---------------------------------------------------------------------------
# Validation and saving (Admin > Library folders)
# ---------------------------------------------------------------------------
class FolderError(ValueError):
    pass


def _is_absolute(path: str) -> bool:
    return ntpath.isabs(path) or path.startswith("\\\\") or posixpath.isabs(path)


def _inside(child: str, parent: str) -> bool:
    c, p = _key(child), _key(parent)
    return c == p or c.startswith(p + "\\")


def validate(proposed: dict[str, list[str]]) -> dict[str, list[str]]:
    """Clean and check a full set of folders. Raises FolderError."""
    clean: dict[str, list[str]] = {}
    for kind in KINDS:
        items = proposed.get(kind) or []
        if not isinstance(items, list):
            raise FolderError(f"{LABELS[kind]}: expected a list of folders")
        folders_ = parse(";".join(str(i) for i in items if i is not None))
        if len(folders_) > MAX_FOLDERS_PER_LIBRARY:
            raise FolderError(f"{LABELS[kind]}: at most {MAX_FOLDERS_PER_LIBRARY} folders")
        for p in folders_:
            if len(p) > 1024:
                raise FolderError(f"{LABELS[kind]}: path too long")
            if not _is_absolute(p):
                raise FolderError(f"{LABELS[kind]}: '{p}' is not a full path (like D:\\Movies or \\\\nas\\media\\Movies)")
            for own in (settings.art_root, settings.metadata_cache_root, settings.transcode_cache_dir):
                if own and (_inside(str(own), p) or _inside(p, str(own))):
                    raise FolderError(f"{LABELS[kind]}: '{p}' overlaps F7FIVE0's own data folder")
        clean[kind] = folders_
    # No folder may appear twice, or sit inside another one, across libraries
    # or within one: the same file would be scanned twice.
    flat = [(k, p) for k in KINDS for p in clean[k]]
    for i, (k1, p1) in enumerate(flat):
        for k2, p2 in flat[i + 1:]:
            if _inside(p1, p2) or _inside(p2, p1):
                a, b = (p1, p2) if len(p1) >= len(p2) else (p2, p1)
                raise FolderError(
                    f"'{a}' ({LABELS[k1] if a == p1 else LABELS[k2]}) is the same as or inside "
                    f"'{b}' ({LABELS[k2] if b == p2 else LABELS[k1]})"
                )
    return clean


def arr_managed(kind: str) -> bool:
    """Radarr / Sonarr / Lidarr owns this library; the folder list is unused."""
    return {
        "movies": bool(settings.radarr_api_key),
        "tv": bool(settings.sonarr_api_key),
        "music": bool(settings.lidarr_api_key),
    }.get(kind, False)


def save(db: Session, proposed: dict[str, list[str]]) -> dict[str, list[str]]:
    """Replace every library's folders. The table becomes the source of
    truth from here on, even for libraries left empty. Files under a folder
    that was removed are marked missing, which takes their items out of the
    library; watch history stays, and adding the folder back restores them."""
    clean = validate(proposed)
    before = all_folders(db)
    for kind in KINDS:
        removed = [p for p in before[kind] if _key(p) not in {_key(n) for n in clean[kind]}]
        if removed and not arr_managed(kind):
            _hide_files_under(db, kind, removed, keep=clean[kind])
    db.execute(delete(Library))
    db.flush()
    # created_at carries the order the admin gave (rows share one transaction,
    # so the server default would make them all equal).
    base = datetime.now(timezone.utc)
    n = 0
    for kind in KINDS:
        for p in clean[kind]:
            db.add(Library(name=LABELS[kind], kind=LibraryKind(kind), root_path=p,
                           created_at=base + timedelta(microseconds=n)))
            n += 1
    db.flush()
    return clean


_MEDIA_KIND = {
    "movies": MediaKind.movie, "tv": MediaKind.episode,
    "music": MediaKind.track, "music_videos": MediaKind.music_video,
}


def _hide_files_under(db: Session, kind: str, removed: list[str], keep: list[str]) -> int:
    def under(path: str, folders_: list[str]) -> bool:
        return any(_inside(path, translate_path(f) or f) for f in folders_)

    n = 0
    rows = db.scalars(select(MediaFile).where(MediaFile.kind == _MEDIA_KIND[kind])).all()
    for mf in rows:
        p = mf.path or ""
        if under(p, removed) and not under(p, keep) and mf.scan_state != ScanState.missing:
            mf.scan_state = ScanState.missing
            n += 1
    return n


@dataclass
class FolderStatus:
    path: str
    reachable: bool


def status(path: str) -> FolderStatus:
    """Whether the server (as the account the API runs under) can open it."""
    try:
        os.listdir(path)
        ok = os.path.isdir(path)
    except OSError:
        ok = False
    return FolderStatus(path=path, reachable=ok)
