r"""The folder scan for the podcasts library.

Layout (the same one server downloads write):

    <root>\Show name\2025-03-01 Episode title.mp3
    <root>\Show name\cover.jpg            (or folder.jpg, or the first embedded image)

Each subfolder of a podcasts folder is a show and each audio file in it an
episode. The show title is the album tag of its first file, else the folder
name. An episode title is the title tag, else the file name; its date is the
date tag, else a leading `YYYY-MM-DD` in the file name, else the file modified
time. A file already linked to an episode (a server download) is matched by its
path and never duplicated, and a folder whose name matches a feed show's folder
joins that show instead of making a local one.

It runs inside `scan_library.scan_all` with the same rules as the other
libraries: it commits every BATCH_SIZE items and at the end, each file imports
inside a savepoint so one bad file loses only itself, and files that disappear
are marked missing, never deleted.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.art import ENTITY_PODCAST, ROLE_COVER
from app.models.media_file import MediaFile, MediaKind
from app.models.podcast import SOURCE_LOCAL, Podcast, PodcastEpisode
from app.services import library_folders, scan_library

log = logging.getLogger("f7five0.podcasts.scan")

_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[\s._-]+|$)")
_SIDECARS = ("cover", "folder", "poster", "artwork", "show")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)).rstrip("\\/")


def _leaf(path: str) -> str:
    """The last part of a path written with either separator, lower case. Works
    the same on Windows and elsewhere, so a share path and a drive path compare."""
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1].lower()


def _tag(tags: dict, *keys: str) -> Optional[str]:
    return scan_library._first(tags, *keys)


def _date_from_text(value: Optional[str]) -> Optional[datetime]:
    """`2025-01-05`, `2025-01-05T10:00:00` or `2025` to a UTC datetime."""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", text)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1), tzinfo=timezone.utc)
    except ValueError:
        return None


def _date_from_name(stem: str) -> Optional[datetime]:
    m = _DATE_PREFIX_RE.match(stem)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None


def _title_from_name(stem: str) -> str:
    return _DATE_PREFIX_RE.sub("", stem, count=1).strip() or stem


def _audio_files(show_dir: str) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(show_dir):
        dirnames[:] = sorted(d for d in dirnames if not scan_library._is_skip_dir(d))
        for name in sorted(filenames):
            if scan_library._ext(name) in scan_library.AUDIO_EXTS:
                out.append(os.path.join(dirpath, name))
    return out


def _find_show(db: Session, show_dir: str) -> Optional[Podcast]:
    """The show this folder belongs to: the one whose folder it is, else a feed
    show whose folder has the same name (a server download tree seen through a
    different path, a drive letter against a share)."""
    shows = db.scalars(select(Podcast).where(Podcast.folder_path.is_not(None))).all()
    here = _norm(show_dir)
    for pod in shows:
        if _norm(pod.folder_path or "") == here:
            return pod
    name = _leaf(show_dir)
    for pod in shows:
        if _leaf(pod.folder_path or "") == name:
            return pod
    return None


def _resolve_show(db: Session, show_dir: str, first_file: str, stats) -> Podcast:
    pod = _find_show(db, show_dir)
    if pod is not None:
        return pod
    tags = scan_library.read_tags(first_file)
    title = _tag(tags, "album") or os.path.basename(show_dir.rstrip("\\/"))
    pod = Podcast(id=uuid.uuid4(), title=title[:512], source=SOURCE_LOCAL, feed_url=None, folder_path=show_dir)
    db.add(pod)
    db.flush()
    stats.podcasts += 1
    return pod


def _import_show_art(db: Session, pod: Podcast, show_dir: str, first_file: str, stats) -> None:
    side = scan_library._find_sidecar(show_dir, _SIDECARS)
    if side:
        scan_library._import_art_file(
            db, entity_kind=ENTITY_PODCAST, entity_id=pod.id, role=ROLE_COVER,
            image_path=side, stats=stats,
        )
    elif not scan_library._has_art(db, ENTITY_PODCAST, pod.id, ROLE_COVER):
        data = scan_library.embedded_cover(first_file)
        if data:
            scan_library._save_art_bytes(
                db, ENTITY_PODCAST, pod.id, ROLE_COVER, data,
                f"embedded:{scan_library._store_path(first_file)}", stats,
            )


def _import_one(db: Session, pod: Podcast, file_path: str, seen: set, stats) -> None:
    """Import one audio file as an episode of `pod`, inside the caller savepoint."""
    path = scan_library._store_path(file_path)
    seen.add(path)
    existing = db.scalar(select(MediaFile).where(MediaFile.path == path))
    if existing is not None and existing.kind == MediaKind.podcast_episode:
        ep = db.get(PodcastEpisode, existing.ref_id)
        if ep is not None:
            # A download, or a file seen before: keep the episode, refresh the file.
            scan_library._upsert_file(db, kind=MediaKind.podcast_episode, ref_id=ep.id, path=path, stats=stats)
            if ep.media_file_id != existing.id:
                ep.media_file_id = existing.id
            if not ep.duration_sec and existing.duration_sec:
                ep.duration_sec = existing.duration_sec
            return

    stem = os.path.splitext(os.path.basename(file_path))[0]
    tags = scan_library.read_tags(file_path)
    title = _tag(tags, "title") or _title_from_name(stem)
    published = (
        _date_from_text(_tag(tags, "date", "originaldate", "year"))
        or _date_from_name(stem)
        or scan_library._mtime(file_path)
        or datetime.now(timezone.utc)
    )
    ep = PodcastEpisode(
        id=uuid.uuid4(), podcast_id=pod.id,
        guid="local:" + hashlib.sha1(_norm(path).encode("utf-8")).hexdigest(),
        title=title[:1024], published_at=published,
    )
    db.add(ep)
    db.flush()
    mf = scan_library._upsert_file(db, kind=MediaKind.podcast_episode, ref_id=ep.id, path=path, stats=stats)
    ep.media_file_id = mf.id
    ep.duration_sec = mf.duration_sec
    stats.podcast_episodes += 1


def scan(db: Session, stats, on_progress=None):
    batch = scan_library._Batcher(db, "podcasts", stats, on_progress)
    roots = library_folders.folders(db, "podcasts")
    for _ri, root in scan_library._reachable(roots, "podcasts"):
        _scan_root(db, root, stats, batch)
    db.flush()
    stats.log_summary("podcasts")
    batch.commit()
    return stats


def _scan_root(db: Session, root: str, stats, batch) -> None:
    seen: set[str] = set()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        log.warning("podcasts folder could not be listed: %r", root)
        return
    for name in names:
        show_dir = os.path.join(root, name)
        if not os.path.isdir(show_dir) or scan_library._is_skip_dir(name):
            continue
        files = _audio_files(show_dir)
        if not files:
            continue
        # The show first, in its own savepoint: a show that cannot be made loses
        # its files for this pass and the scan moves on.
        sp = db.begin_nested()
        try:
            pod = _resolve_show(db, show_dir, files[0], stats)
            _import_show_art(db, pod, show_dir, files[0], stats)
            sp.commit()
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            scan_library._record_file_error(show_dir, exc, stats)
            for f in files:
                seen.add(scan_library._store_path(f))
                batch.item_done()
            continue
        for file_path in files:
            sp = db.begin_nested()
            try:
                _import_one(db, pod, file_path, seen, stats)
                sp.commit()
            except Exception as exc:  # noqa: BLE001
                sp.rollback()
                seen.add(scan_library._store_path(file_path))
                scan_library._record_file_error(file_path, exc, stats)
            batch.item_done()
    scan_library._mark_missing_under(db, MediaKind.podcast_episode, root, seen, stats)
