"""Admin > Library folders > Path mappings: drive letters the services cannot see.

Radarr, Sonarr and Lidarr report paths on a drive letter (`N:\\Movies\\...`) that
is mapped only in one person's Windows login. The F7FIVE0 services run as
LocalSystem, which has no `N:`, so every such file ends up missing or refused
and the library looks nearly empty. A mapping tells the services what the letter
means: `N:` is `\\\\fuegonas\\The Hive`.

Mappings are saved in the database (`app_settings` key `path_mappings`), so an
admin can add and remove them in Admin without editing `.env` or restarting.
`path_map.translate` reads them (and the `.env` `PATH_REWRITE_RULES`, which keep
working underneath), and the API and the stream gateway each reload them on a
short timer.

Saving a mapping also rewrites the paths already stored in `media_files`, in
place, so a movie keeps its row and with it its watch progress and history.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.media_file import MediaFile
from app.models.playback import WatchHistory, WatchProgress
from app.services import app_settings, arr_settings, path_map

log = logging.getLogger("f7five0.path_mappings")

_DRIVE = re.compile(r"^[A-Za-z]:$")
_UNC = re.compile(r"^\\\\[^\\/]+\\[^\\/]+(\\.*)?$")
_ABS = re.compile(r"^[A-Za-z]:\\.+")


class MappingError(ValueError):
    """A mapping the admin typed that cannot be saved. `code` is for the API;
    the message is plain words for the form."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def clean(src: str, dst: str) -> tuple[str, str]:
    """The drive letter ("N:") and its target, or MappingError."""
    s = (src or "").strip().rstrip("\\/")
    d = (dst or "").strip().rstrip("\\/")
    if not _DRIVE.match(s):
        raise MappingError("bad_drive", "The drive must be one letter and a colon, like N:.")
    if not (_UNC.match(d) or _ABS.match(d)):
        raise MappingError(
            "bad_target",
            "The target must be a network path like \\\\server\\share, or a full folder path like D:\\Media.",
        )
    s = s[0].upper() + ":"
    if d[:2].upper() == s:
        raise MappingError("loop", "A drive cannot be mapped to itself.")
    return s, d


def read(db: Session) -> list[dict]:
    """The saved mappings, in the order they were added."""
    stored = app_settings.get(db, path_map.DB_KEY) or {}
    out: list[dict] = []
    for item in stored.get("mappings") or []:
        if isinstance(item, dict) and item.get("src") and item.get("dst"):
            out.append({"src": str(item["src"]), "dst": str(item["dst"])})
    return out


def _write(db: Session, mappings: list[dict]) -> None:
    app_settings.put(db, path_map.DB_KEY, {"mappings": mappings})
    # This process sees the change now; the other one on its next reload.
    path_map.invalidate()


def save(db: Session, src: str, dst: str) -> dict:
    """Add (or change the target of) a mapping, then rewrite the stored paths.
    Does not commit. Returns what was rewritten: {rewritten, merged}."""
    s, d = clean(src, dst)
    mappings = [m for m in read(db) if m["src"].lower() != s.lower()]
    mappings.append({"src": s, "dst": d})
    _write(db, mappings)
    return rewrite_existing(db, s, d)


def remove(db: Session, src: str) -> bool:
    """Take a mapping away. Paths already rewritten stay as they are (they are
    valid network paths). Does not commit. False when there was no such mapping."""
    s = (src or "").strip().rstrip("\\/").upper()
    before = read(db)
    after = [m for m in before if m["src"].upper() != s]
    if len(after) == len(before):
        return False
    _write(db, after)
    return True


def _history_count(db: Session, media_file_id) -> int:
    progress = db.scalar(
        select(func.count()).select_from(WatchProgress).where(WatchProgress.media_file_id == media_file_id)
    ) or 0
    history = db.scalar(
        select(func.count()).select_from(WatchHistory).where(WatchHistory.media_file_id == media_file_id)
    ) or 0
    return progress + history


def _merge_into(db: Session, keep: MediaFile, drop: MediaFile) -> None:
    """Fold `drop` into `keep`: its history moves over, then the row goes."""
    keep_users = set(db.scalars(
        select(WatchProgress.user_id).where(WatchProgress.media_file_id == keep.id)
    ).all())
    for wp in db.scalars(select(WatchProgress).where(WatchProgress.media_file_id == drop.id)).all():
        if wp.user_id not in keep_users:
            db.execute(
                update(WatchProgress)
                .where(WatchProgress.user_id == wp.user_id, WatchProgress.media_file_id == drop.id)
                .values(media_file_id=keep.id)
            )
    db.execute(
        update(WatchHistory).where(WatchHistory.media_file_id == drop.id).values(media_file_id=keep.id)
    )
    db.flush()
    db.expire(drop)
    db.delete(drop)
    db.flush()


def rewrite_existing(db: Session, src: str, dst: str) -> dict:
    """Rewrite the `media_files` paths that start with `src` to start with `dst`,
    in place. A row keeps its id, so its watch progress and history survive.

    When the rewritten path is already a row of its own (a sync stored the same
    file under its UNC path), the two are merged and the row that has history
    wins; with history on both, the already-synced row wins and takes the other's
    history. Does not commit."""
    rows = db.scalars(
        select(MediaFile).where(func.lower(func.substr(MediaFile.path, 1, len(src))) == src.lower())
    ).all()
    rewritten = 0
    merged = 0
    for mf in rows:
        new_path = path_map.apply_rule(mf.path, src, dst)
        if new_path is None or new_path == mf.path:
            continue
        other = db.scalar(select(MediaFile).where(MediaFile.path == new_path, MediaFile.id != mf.id))
        if other is None:
            mf.path = new_path
            db.flush()
            rewritten += 1
            continue
        mine, theirs = _history_count(db, mf.id), _history_count(db, other.id)
        if mine > 0 and theirs == 0:
            _merge_into_renamed(db, keep=mf, drop=other, new_path=new_path)
        else:
            _merge_into(db, keep=other, drop=mf)
        merged += 1
    if rewritten or merged:
        log.info("path mapping %s -> %s: rewrote %d stored paths, merged %d", src, dst, rewritten, merged)
    return {"rewritten": rewritten, "merged": merged}


def _merge_into_renamed(db: Session, *, keep: MediaFile, drop: MediaFile, new_path: str) -> None:
    """`keep` (the row with history) takes over `drop`'s path."""
    _merge_into(db, keep=keep, drop=drop)
    keep.path = new_path
    db.flush()


# ---------------------------------------------------------------------------
# *arr root folders: can the service open them?
# ---------------------------------------------------------------------------
_APP_LABEL = {"radarr": "Radarr", "sonarr": "Sonarr", "lidarr": "Lidarr"}


def _is_dir(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def root_report(app: str, raw_path: str, db: Optional[Session] = None) -> dict:
    """One root folder the app reported: where it says it is, where the service
    would look, and whether the service can open it."""
    translated = path_map.translate(raw_path, db) or raw_path
    reachable = _is_dir(translated)
    drive = None
    if not reachable and translated == raw_path:
        m = re.match(r"^([A-Za-z]:)[\\/]", raw_path or "")
        drive = m.group(1).upper() if m else None
    return {
        "app": app,
        "label": _APP_LABEL.get(app, app),
        "path": raw_path,
        "translated": translated,
        "mapped": translated != raw_path,
        "reachable": reachable,
        # The drive letter the service cannot see, when that is why.
        "drive": drive,
    }


def arr_roots(db: Session, client_for) -> dict:
    """Every configured app's root folders, with reachability. `client_for(app)`
    returns the app's client (a context manager with `root_folders()`); an app
    that cannot be asked is listed under `errors` instead of failing the page."""
    try:
        from app.services import nas_auth

        nas_auth.ensure_all(db)
    except Exception:
        log.debug("could not connect the saved NAS sign-ins", exc_info=True)
    roots: list[dict] = []
    errors: list[dict] = []
    for app in arr_settings.APPS:
        if not arr_settings.configured(app):
            continue
        try:
            with client_for(app) as client:
                folders = client.root_folders()
        except Exception as exc:  # an *arr that is down is a note, not a failure
            errors.append({"app": app, "label": _APP_LABEL.get(app, app), "error": str(exc)[:200]})
            continue
        seen: set[str] = set()
        for f in folders:
            path = str(f.get("path") or "") if isinstance(f, dict) else ""
            if path and path.lower() not in seen:
                seen.add(path.lower())
                roots.append(root_report(app, path, db))
    return {"roots": roots, "errors": errors}
