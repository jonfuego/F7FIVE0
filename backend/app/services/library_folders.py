r"""Library source folders: one or more per library.

Where the folders come from:

- The `libraries` table, one row per folder (kind + root_path). Admin >
  Library folders writes it. Once the table has any row it is the only
  source, for every library: a library with no rows is not configured.
- Otherwise the `.env` keys LIBRARY_ROOT_MOVIES / _TV / _MUSIC /
  _MUSIC_VIDEOS / _PODCASTS. Each takes one folder or several separated by `;`
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

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.library import Library, LibraryFolder, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services import arr_settings
from app.services.path_map import translate as translate_path

KINDS: tuple[str, ...] = ("movies", "tv", "music", "music_videos", "podcasts")
LABELS = {
    "movies": "Movies", "tv": "TV shows", "music": "Music", "music_videos": "Music videos",
    "podcasts": "Podcasts",
}
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
    """Effective folders for one kind, across every library of that kind.

    Reads `library_folders` joined to `libraries` by kind once any library
    exists; otherwise falls back to the `LIBRARY_ROOT_*` env keys."""
    if db is not None and db_managed(db):
        rows = db.execute(
            select(LibraryFolder.path)
            .join(Library, Library.id == LibraryFolder.library_id)
            .where(Library.kind == LibraryKind(kind))
            .order_by(Library.sort_order, Library.created_at, LibraryFolder.created_at, LibraryFolder.path)
        ).all()
        return [r[0] for r in rows]
    return env_folders(kind)


def all_folders(db: Optional[Session]) -> dict[str, list[str]]:
    return {k: folders(db, k) for k in KINDS}


def _library_for_kind(db: Session, kind: str) -> Optional[Library]:
    """The first (lowest sort_order) library of a kind, or None."""
    return db.scalars(
        select(Library).where(Library.kind == LibraryKind(kind))
        .order_by(Library.sort_order, Library.created_at)
    ).first()


def library_for_path(db: Session, path: Optional[str]) -> Optional[uuid.UUID]:
    """The id of the library whose folder contains `path` (longest match), or
    None. Compares the stored path (already drive->UNC translated by the scanner)
    against each folder in both its raw and translated form, so a folder typed as
    a drive letter still matches a media path stored as a UNC path."""
    if not path:
        return None
    rows = db.execute(select(LibraryFolder.library_id, LibraryFolder.path)).all()
    if not rows:
        return None
    target = _key(path)
    best_id: Optional[uuid.UUID] = None
    best_len = -1
    for lib_id, folder in rows:
        for cand in (folder, translate_path(folder, db) or folder):
            fk = _key(cand)
            if target == fk or target.startswith(fk + "\\"):
                if len(fk) > best_len:
                    best_id, best_len = lib_id, len(fk)
    return best_id


def backfill_media_file_library_id(db: Session, batch_size: int = 500) -> int:
    """Fill `media_files.library_id` for rows that still have none, by matching
    the stored path to a library folder. Batched and rerunnable: a row whose path
    matches no folder is left null (visible to all) and tried again next run.
    Returns the number of rows stamped. The caller commits."""
    folder_rows = db.execute(select(LibraryFolder.library_id, LibraryFolder.path)).all()
    if not folder_rows:
        return 0
    # Pre-compute normalized folder prefixes (raw and translated) per library.
    prefixes: list[tuple[str, uuid.UUID]] = []
    for lib_id, folder in folder_rows:
        for cand in {folder, translate_path(folder, db) or folder}:
            prefixes.append((_key(cand), lib_id))

    def match(path: str) -> Optional[uuid.UUID]:
        target = _key(path)
        best_id: Optional[uuid.UUID] = None
        best_len = -1
        for fk, lib_id in prefixes:
            if target == fk or target.startswith(fk + "\\"):
                if len(fk) > best_len:
                    best_id, best_len = lib_id, len(fk)
        return best_id

    filled = 0
    rows = db.scalars(
        select(MediaFile).where(MediaFile.library_id.is_(None)).limit(batch_size)
    ).all()
    for mf in rows:
        lib_id = match(mf.path or "")
        if lib_id is not None:
            mf.library_id = lib_id
            filled += 1
    if filled:
        db.flush()
    return filled


def ensure_seeded(db: Session) -> int:
    """Create one library per kind that has env folders but no library row yet.

    A no-op once the table is managed (an admin saved folders): the env fallback
    is off from then on, so there is nothing to seed. On an install still running
    from `LIBRARY_ROOT_*`, this makes one library per kind from the env folders at
    startup and before each scan, so `library_id` is always assignable and access
    control is consistent. Returns the number of libraries created. The caller
    commits."""
    if db_managed(db):
        return 0
    created = 0
    base = datetime.now(timezone.utc)
    for i, kind in enumerate(KINDS):
        paths = env_folders(kind)
        if not paths:
            continue
        lib = Library(name=LABELS[kind], kind=LibraryKind(kind), sort_order=0,
                      created_at=base + timedelta(microseconds=i))
        db.add(lib)
        db.flush()
        for j, p in enumerate(paths):
            db.add(LibraryFolder(library_id=lib.id, path=p,
                                 created_at=base + timedelta(microseconds=i * 100 + j)))
        created += 1
    if created:
        db.flush()
    return created


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
        "movies": arr_settings.configured("radarr"),
        "tv": arr_settings.configured("sonarr"),
        "music": arr_settings.configured("lidarr"),
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
    # One named library per kind owns its folders. Keep the library row (and its
    # id, so user access and sort order survive an edit) and replace its folders.
    base = datetime.now(timezone.utc)
    n = 0
    for i, kind in enumerate(KINDS):
        lib = _library_for_kind(db, kind)
        if lib is None:
            lib = Library(name=LABELS[kind], kind=LibraryKind(kind), sort_order=0,
                          created_at=base + timedelta(microseconds=i))
            db.add(lib)
            db.flush()
        db.execute(delete(LibraryFolder).where(LibraryFolder.library_id == lib.id))
        for p in clean[kind]:
            db.add(LibraryFolder(library_id=lib.id, path=p,
                                 created_at=base + timedelta(microseconds=1000 + n)))
            n += 1
    db.flush()
    return clean


_MEDIA_KIND = {
    "movies": MediaKind.movie, "tv": MediaKind.episode,
    "music": MediaKind.track, "music_videos": MediaKind.music_video,
    "podcasts": MediaKind.podcast_episode,
}


def _hide_files_under(db: Session, kind: str, removed: list[str], keep: list[str]) -> int:
    def under(path: str, folders_: list[str]) -> bool:
        return any(_inside(path, translate_path(f, db) or f) for f in folders_)

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
    # "ok", or why it can't be opened. Local paths: "not_found" /
    # "access_denied". UNC shares reuse the NAS reason codes
    # (nas_auth.reason_for_code): "bad_credentials", "unreachable",
    # "share_not_found", "access_denied", "credential_conflict",
    # "account_blocked", "error".
    reason: str = "ok"
    # For a UNC folder, the NAS username signed in for its server, or None.
    signed_in_as: Optional[str] = None


def status(path: str, db: Optional[Session] = None) -> FolderStatus:
    """Whether the server (as the account the F7FIVE0 services run under) can
    open the folder, and if not, why. For a UNC share, connect any saved NAS
    sign-in first so a share that just needs reconnecting comes back as
    reachable, and report who it is signed in as."""
    # Local import avoids a circular import: nas_auth reads library folders.
    from app.services import nas_auth

    unc = nas_auth.is_unc_path(path)
    signed_in_as = nas_auth.username_for(db, path) if (unc and db is not None) else None
    if unc:
        # Reconnect this server's shares under our logon session if a sign-in
        # is saved. Cheap when already connected; a no-op off Windows.
        nas_auth.ensure_all(db)

    try:
        os.listdir(path)
        ok = os.path.isdir(path)
        reason = "ok" if ok else ("error" if unc else "not_found")
    except OSError as exc:
        ok = False
        if unc:
            winerror = getattr(exc, "winerror", None)
            reason = nas_auth.reason_for_code(winerror) if winerror else "unreachable"
        else:
            reason = "access_denied" if isinstance(exc, PermissionError) else "not_found"
    return FolderStatus(path=path, reachable=ok, reason=reason, signed_in_as=signed_in_as)
