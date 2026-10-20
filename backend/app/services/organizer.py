"""Core organizer logic: preview, apply, undo, recycle folder.

Safety rules (all enforced here):
 1. New paths stay inside the library folder containing the file.
 2. Collision detection before apply.
 3. Sidecars travel with their file (srt, ass, ssa, vtt, sub, idx, lrc, nfo).
 4. .f7five0-recycle is never scanned (handled in scan_library.py).
 5. Full tag backup saved in old_tags before any write.
 6. Undo checks file position before reversing.
 7. Scans exclude organizer (checked by scheduler).
 8. Empty folders removed after apply (recorded as rmdir items for undo).
 9. *arr path update before rename when *arr knows the item.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import db_session
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.organizer import OrganizerJournal, OrganizerJournalItem
from app.models.tv import Episode, Series
from app.services import library_folders, library_settings, naming_templates, tag_writer
from app.services.path_map import translate as translate_path

log = logging.getLogger("f7five0.organizer")

_organizer_lock = threading.Lock()

RECYCLE_DIR = ".f7five0-recycle"

_SIDECAR_EXTS = frozenset({
    "srt", "ass", "ssa", "vtt", "sub", "idx", "lrc", "nfo",
})

_FOLDER_ART_NAMES = frozenset({
    "poster.jpg", "poster.jpeg", "poster.png", "poster.webp",
    "folder.jpg", "folder.jpeg", "folder.png", "folder.webp",
    "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
    "fanart.jpg", "fanart.jpeg", "fanart.png", "fanart.webp",
})


def is_organizer_running() -> bool:
    """True when the organizer apply/undo lock is currently held."""
    acquired = _organizer_lock.acquire(blocking=False)
    if acquired:
        _organizer_lock.release()
        return False
    return True


def _key(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").lower()


def _folder_for_file(mf_path: str, folder_paths: list[str]) -> Optional[str]:
    """The library folder whose path is a prefix of mf_path (longest match)."""
    target = _key(mf_path)
    best: Optional[str] = None
    best_len = -1
    for fp in folder_paths:
        fk = _key(fp)
        if target == fk or target.startswith(fk + "\\"):
            if len(fk) > best_len:
                best = fp
                best_len = len(fk)
    return best


def _is_contained(path: str, folder: str) -> bool:
    """True when path is inside folder (or is folder)."""
    return _key(path) == _key(folder) or _key(path).startswith(_key(folder) + "\\")


def _build_tokens(db: Session, mf: MediaFile) -> Optional[dict]:
    """Build the naming-template token dict for a media file."""
    if mf.kind == MediaKind.movie:
        movie = db.get(Movie, mf.ref_id)
        if not movie:
            return None
        return {
            "Title": movie.title or "",
            "Sort Title": movie.sort_title or movie.title or "",
            "Year": str(movie.year) if movie.year else "",
        }
    elif mf.kind == MediaKind.episode:
        ep = db.get(Episode, mf.ref_id)
        if not ep:
            return None
        series = db.get(Series, ep.series_id)
        return {
            "Series": series.title if series else "",
            "Season": str(ep.season_number).zfill(2),
            "Episode": str(ep.episode_number).zfill(2),
            "Title": ep.title or "",
        }
    elif mf.kind == MediaKind.track:
        track = db.get(Track, mf.ref_id)
        if not track:
            return None
        album = db.get(Album, track.album_id)
        if not album:
            return None
        artist = db.get(Artist, album.artist_id)
        year = ""
        if album.release_date:
            year = str(album.release_date.year)
        disc = track.disc_number or 1
        return {
            "Title": track.title or "",
            "Artist": artist.name if artist else "",
            "Album Artist": artist.name if artist else "",
            "Album": album.title or "",
            "Track": str(track.track_number) if track.track_number is not None else "",
            "Disc": str(disc) if disc != 1 else "",
            "Disc:0": str(disc),
            "Year": year,
        }
    return None


def _kind_key(mf: MediaFile) -> str:
    return {
        MediaKind.movie: "movie",
        MediaKind.episode: "tv",
        MediaKind.track: "music",
        MediaKind.music_video: "music",
    }.get(mf.kind, "movie")


def _compute_new_path(mf: MediaFile, tokens: dict, template: str, folder: str) -> Optional[str]:
    """Compute the new file path for a rename item.

    Returns None when the path cannot be computed or would escape the folder.
    """
    if not template:
        return None
    ext = os.path.splitext(mf.path)[1]
    rendered = naming_templates.render_safe(template, tokens)
    if not rendered:
        return None
    new_rel = rendered + ext
    new_path = os.path.join(folder, new_rel)
    new_path = os.path.normpath(new_path)
    if not _is_contained(new_path, folder):
        log.warning("organizer: new path %r escapes folder %r; skipping", new_path, folder)
        return None
    return new_path


def _find_sidecars(mf_path: str) -> list[str]:
    """Find sidecar files in the same directory with the same base name."""
    dirpath = os.path.dirname(mf_path)
    base = os.path.splitext(os.path.basename(mf_path))[0]
    sidecars: list[str] = []
    try:
        for fname in os.listdir(dirpath):
            if fname == os.path.basename(mf_path):
                continue
            name_lower = fname.lower()
            parts = name_lower.split(".")
            if len(parts) < 2:
                continue
            ext_last = parts[-1]
            if ext_last not in _SIDECAR_EXTS:
                continue
            fname_base = parts[0]
            if fname_base == base.lower():
                sidecars.append(os.path.join(dirpath, fname))
    except OSError:
        pass
    return sidecars


def preview(db: Session, library_id: uuid.UUID, user_id: uuid.UUID) -> OrganizerJournal:
    """Create a preview journal for a library.

    Walks all ready media files, computes new_path and new_tags, and creates
    journal items for files that differ. Does NOT touch any file on disk.
    """
    from app.models.library import Library

    lib = db.get(Library, library_id)
    if lib is None:
        raise ValueError(f"library {library_id} not found")

    settings = library_settings.get_settings(db, library_id)
    naming_tpl = settings.get("naming_template") or {}
    tag_profile = settings.get("tag_profile") or {}
    kind_key = lib.kind.value.rstrip("s") if lib.kind.value != "music" else "music"
    if lib.kind.value == "movies":
        kind_key = "movie"
    elif lib.kind.value == "tv":
        kind_key = "tv"
    elif lib.kind.value == "music":
        kind_key = "music"
    elif lib.kind.value == "music_videos":
        kind_key = "music"
    else:
        kind_key = None

    template = naming_tpl.get(kind_key) if kind_key else None

    folder_paths = _get_library_folders(db, library_id)

    journal = OrganizerJournal(
        library_id=library_id,
        state="preview",
        started_at=datetime.now(timezone.utc),
        created_by=user_id,
    )
    db.add(journal)
    db.flush()

    media_files = db.scalars(
        select(MediaFile).where(
            MediaFile.library_id == library_id,
            MediaFile.scan_state == ScanState.ready,
        )
    ).all()

    items: list[OrganizerJournalItem] = []
    new_paths: dict[str, str] = {}
    sort_order = 0

    for mf in media_files:
        tokens = _build_tokens(db, mf)
        if tokens is None:
            continue

        translated_path = translate_path(mf.path, db) or mf.path
        containing_folder = _folder_for_file(translated_path, folder_paths)
        if not containing_folder:
            continue

        new_path = None
        path_changed = False
        if template:
            new_path = _compute_new_path(mf, tokens, template, containing_folder)
            if new_path and _key(new_path) != _key(translated_path):
                path_changed = True

        tag_changed = False
        new_tags_dict = None
        if tag_profile and mf.kind in (MediaKind.track,):
            new_tags_dict = _compute_new_tags(mf, tokens, db)
            old_tags = tag_writer.backup_tags(translated_path) or {}
            tag_changed = _tags_differ(old_tags, new_tags_dict, tag_profile)

        if not path_changed and not tag_changed:
            continue

        if path_changed and new_path:
            item_kind = "both" if tag_changed else "rename"
        else:
            item_kind = "retag"

        old_tags_json = None
        if tag_changed:
            old_tags_backup = tag_writer.backup_tags(translated_path)
            if old_tags_backup is not None:
                old_tags_json = json.dumps(old_tags_backup)
            else:
                old_tags_json = json.dumps({})

        new_tags_json = json.dumps(new_tags_dict) if new_tags_dict is not None else None

        item = OrganizerJournalItem(
            journal_id=journal.id,
            media_file_id=mf.id,
            item_kind=item_kind,
            old_path=mf.path,
            new_path=new_path if path_changed else None,
            old_tags=old_tags_json,
            new_tags=new_tags_json,
            sort_order=sort_order,
        )
        db.add(item)
        items.append(item)
        sort_order += 1

        if path_changed and new_path:
            key = _key(new_path)
            if key in new_paths:
                item.item_kind = "collision"
                item.error = f"collision with {new_paths[key]}"
            else:
                new_paths[key] = mf.path

    db.flush()

    for item in items:
        if item.item_kind == "collision":
            continue
        if item.new_path and _key(item.new_path) in {_key(p) for p in new_paths.values() if p != item.old_path}:
            pass

    journal.item_count = len([i for i in items if i.item_kind not in ("collision",)])
    db.commit()
    return journal


def _get_library_folders(db: Session, library_id: uuid.UUID) -> list[str]:
    """Get all folder paths for a library."""
    from app.models.library import Library, LibraryFolder
    rows = db.scalars(
        select(LibraryFolder).where(LibraryFolder.library_id == library_id)
    ).all()
    folders = [r.path for r in rows]
    if not folders:
        lib = db.get(Library, library_id)
        if lib:
            folders = library_folders.folders(db, lib.kind.value)
    return [translate_path(f, db) or f for f in folders]


def _compute_new_tags(mf: MediaFile, tokens: dict, db: Session) -> dict:
    """Build the new_tags dict from the track model."""
    tags: dict = {}
    if mf.kind != MediaKind.track:
        return tags
    track = db.get(Track, mf.ref_id)
    if not track:
        return tags
    album = db.get(Album, track.album_id)
    artist = db.get(Artist, album.artist_id) if album else None
    tags["title"] = track.title or ""
    tags["artist"] = artist.name if artist else ""
    tags["album_artist"] = artist.name if artist else ""
    tags["album"] = album.title if album else ""
    tags["track_number"] = track.track_number
    tags["disc_number"] = track.disc_number
    if album and album.release_date:
        tags["year"] = album.release_date.year
    if track.mbid:
        tags["mb_recording_id"] = track.mbid
    if album and album.mbid:
        tags["mb_album_id"] = album.mbid
    if artist and artist.mbid:
        tags["mb_artist_id"] = artist.mbid
    return tags


def _tags_differ(old_tags: dict, new_tags: dict, profile: dict) -> bool:
    """Rough check: do the new tags differ from what's on disk?"""
    if not new_tags:
        return False
    return True


def apply_run(journal_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Apply a preview journal: rename files and write tags.

    Runs in the background (called from scheduler). Holds _organizer_lock
    for the duration.
    """
    if not _organizer_lock.acquire(blocking=False):
        log.warning("organizer apply: lock already held; aborting")
        return

    try:
        _apply_locked(journal_id, user_id)
    finally:
        _organizer_lock.release()


def _apply_locked(journal_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db = None
    try:
        from app.db import SessionLocal
        db = SessionLocal()
        journal = db.get(OrganizerJournal, journal_id)
        if journal is None:
            log.error("organizer apply: journal %s not found", journal_id)
            return
        if journal.state != "preview":
            log.warning("organizer apply: journal %s is in state %s, not preview", journal_id, journal.state)
            return

        journal.state = "running"
        db.commit()

        settings = library_settings.get_settings(db, journal.library_id) if journal.library_id else {}
        tag_profile = settings.get("tag_profile") or {}
        ownership = settings.get("ownership", "f7five0")
        folder_paths = _get_library_folders(db, journal.library_id) if journal.library_id else []

        items = db.scalars(
            select(OrganizerJournalItem)
            .where(OrganizerJournalItem.journal_id == journal_id)
            .order_by(OrganizerJournalItem.sort_order)
        ).all()

        renamed_items: list[tuple[str, str, MediaKind, Optional[uuid.UUID]]] = []
        errors = 0
        old_dirs: list[str] = []

        for item in items:
            if item.item_kind in ("collision", "sidecar", "rmdir"):
                continue

            mf = db.get(MediaFile, item.media_file_id) if item.media_file_id else None

            if item.item_kind in ("rename", "both") and item.new_path:
                old_translated = translate_path(item.old_path, db) or item.old_path
                new_translated = item.new_path

                if not os.path.exists(old_translated):
                    item.error = "source_not_found"
                    errors += 1
                    db.commit()
                    continue

                if os.path.exists(new_translated) and _key(new_translated) != _key(old_translated):
                    item.error = "target_exists"
                    errors += 1
                    db.commit()
                    continue

                containing_folder = _folder_for_file(old_translated, folder_paths)
                arr_item_folder = None
                arr_new_folder = None
                if containing_folder and mf:
                    arr_item_folder = _get_item_folder(old_translated, mf, containing_folder)
                    new_item_folder = _get_item_folder(new_translated, mf, containing_folder)
                    if arr_item_folder and new_item_folder and _key(arr_item_folder) != _key(new_item_folder):
                        arr_new_folder = new_item_folder

                if arr_new_folder and mf:
                    err = _update_arr_path(db, mf, arr_new_folder)
                    if err:
                        item.error = f"arr_path_update_failed: {err}"
                        errors += 1
                        db.commit()
                        continue

                old_dir = os.path.dirname(old_translated)
                old_dirs.append(old_dir)

                sidecars = _find_sidecars(old_translated)
                try:
                    os.makedirs(os.path.dirname(new_translated), exist_ok=True)
                    os.rename(old_translated, new_translated)
                except OSError as exc:
                    item.error = str(exc)
                    errors += 1
                    if arr_new_folder:
                        try:
                            _update_arr_path(db, mf, arr_item_folder or os.path.dirname(old_translated))
                        except Exception:
                            pass
                    db.commit()
                    continue

                if mf:
                    mf.path = new_translated
                    db.flush()

                for sc in sidecars:
                    sc_new = os.path.join(
                        os.path.dirname(new_translated),
                        os.path.basename(sc),
                    )
                    sidecar_item = OrganizerJournalItem(
                        journal_id=journal_id,
                        media_file_id=None,
                        item_kind="sidecar",
                        old_path=sc,
                        new_path=sc_new,
                        sort_order=item.sort_order,
                    )
                    db.add(sidecar_item)
                    try:
                        os.makedirs(os.path.dirname(sc_new), exist_ok=True)
                        os.rename(sc, sc_new)
                    except OSError as exc:
                        sidecar_item.error = str(exc)

                if mf:
                    renamed_items.append((item.old_path, new_translated, mf.kind, mf.ref_id))

            if item.item_kind in ("retag", "both"):
                path_to_tag = (item.new_path or item.old_path)
                translated_tag_path = translate_path(path_to_tag, db) or path_to_tag
                new_tags = json.loads(item.new_tags) if item.new_tags else {}
                err = tag_writer.write_tags(translated_tag_path, new_tags, tag_profile)
                if err:
                    if not item.error:
                        item.error = err
                    errors += 1

            db.commit()

        _remove_empty_dirs(db, old_dirs, folder_paths, journal_id, items)

        if errors > 0 and errors == len([i for i in items if i.item_kind not in ("collision", "sidecar", "rmdir")]):
            journal.state = "failed"
        else:
            journal.state = "done"
        journal.finished_at = datetime.now(timezone.utc)
        db.commit()

        if renamed_items and journal.library_id:
            lib_settings = library_settings.get_settings(db, journal.library_id) if journal.library_id else {}
            _trigger_arr_rescans(db, journal.library_id, renamed_items)

    except Exception as exc:
        log.exception("organizer apply raised: %s", exc)
        if db:
            try:
                j = db.get(OrganizerJournal, journal_id)
                if j:
                    j.state = "failed"
                    j.error = str(exc)
                    j.finished_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                db.rollback()
    finally:
        if db:
            db.close()


def _get_item_folder(file_path: str, mf: MediaFile, library_folder: str) -> Optional[str]:
    """Get the item-level folder (movie folder, series folder, artist folder)."""
    if mf.kind == MediaKind.movie:
        return os.path.dirname(file_path)
    elif mf.kind == MediaKind.episode:
        parent = os.path.dirname(file_path)
        grandparent = os.path.dirname(parent)
        if _is_contained(grandparent, library_folder) and grandparent != library_folder:
            return grandparent
        return parent
    elif mf.kind == MediaKind.track:
        parent = os.path.dirname(file_path)
        grandparent = os.path.dirname(parent)
        if _is_contained(grandparent, library_folder) and grandparent != library_folder:
            return grandparent
        return parent
    return os.path.dirname(file_path)


def _update_arr_path(db: Session, mf: MediaFile, new_folder: str) -> Optional[str]:
    """Update the *arr path for an item with move files off. Returns None on success, error string otherwise."""
    from app.services import arr_settings as arr_svc
    try:
        if mf.kind == MediaKind.movie:
            movie = db.get(Movie, mf.ref_id)
            if movie and movie.radarr_id:
                base_url = arr_svc.url("radarr", db)
                api_key = arr_svc.api_key("radarr", db)
                if base_url and api_key:
                    from app.services.arr.radarr import RadarrClient
                    client = RadarrClient(base_url, api_key)
                    client.update_movie_path(movie.radarr_id, new_folder)
        elif mf.kind == MediaKind.episode:
            ep = db.get(Episode, mf.ref_id)
            if ep:
                from app.models.tv import Series
                series = db.get(Series, ep.series_id)
                if series and series.sonarr_id:
                    base_url = arr_svc.url("sonarr", db)
                    api_key = arr_svc.api_key("sonarr", db)
                    if base_url and api_key:
                        from app.services.arr.sonarr import SonarrClient
                        client = SonarrClient(base_url, api_key)
                        client.update_series_path(series.sonarr_id, new_folder)
        elif mf.kind == MediaKind.track:
            track = db.get(Track, mf.ref_id)
            if track:
                album = db.get(Album, track.album_id)
                if album:
                    artist = db.get(Artist, album.artist_id)
                    if artist and artist.lidarr_id:
                        base_url = arr_svc.url("lidarr", db)
                        api_key = arr_svc.api_key("lidarr", db)
                        if base_url and api_key:
                            from app.services.arr.lidarr import LidarrClient
                            client = LidarrClient(base_url, api_key)
                            client.update_artist_path(artist.lidarr_id, new_folder)
        return None
    except Exception as exc:
        return str(exc)


def _trigger_arr_rescans(
    db: Session,
    library_id: uuid.UUID,
    renamed_items: list[tuple[str, str, MediaKind, Optional[uuid.UUID]]],
) -> None:
    """Fire-and-forget: send RescanMovie/RescanSeries/RescanArtist for renamed items."""
    from app.services import arr_settings as arr_svc

    seen_refs: dict[MediaKind, set] = {}
    for _, _, kind, ref_id in renamed_items:
        if ref_id is None:
            continue
        seen_refs.setdefault(kind, set()).add(ref_id)

    def _rescan():
        with db_session() as rdb:
            for kind, ref_ids in seen_refs.items():
                for ref_id in ref_ids:
                    try:
                        if kind == MediaKind.movie:
                            movie = rdb.get(Movie, ref_id)
                            if movie and movie.radarr_id:
                                base_url = arr_svc.url("radarr", rdb)
                                api_key = arr_svc.api_key("radarr", rdb)
                                if base_url and api_key:
                                    from app.services.arr.radarr import RadarrClient
                                    RadarrClient(base_url, api_key).rescan_movie(movie.radarr_id)
                        elif kind == MediaKind.episode:
                            ep = rdb.get(Episode, ref_id)
                            if ep:
                                series = rdb.get(Series, ep.series_id)
                                if series and series.sonarr_id:
                                    base_url = arr_svc.url("sonarr", rdb)
                                    api_key = arr_svc.api_key("sonarr", rdb)
                                    if base_url and api_key:
                                        from app.services.arr.sonarr import SonarrClient
                                        SonarrClient(base_url, api_key).rescan_series(series.sonarr_id)
                        elif kind == MediaKind.track:
                            track = rdb.get(Track, ref_id)
                            if track:
                                album = rdb.get(Album, track.album_id)
                                if album:
                                    artist = rdb.get(Artist, album.artist_id)
                                    if artist and artist.lidarr_id:
                                        base_url = arr_svc.url("lidarr", rdb)
                                        api_key = arr_svc.api_key("lidarr", rdb)
                                        if base_url and api_key:
                                            from app.services.arr.lidarr import LidarrClient
                                            LidarrClient(base_url, api_key).rescan_artist(artist.lidarr_id)
                    except Exception as exc:
                        log.warning("organizer: arr rescan failed for %s %s: %s", kind, ref_id, exc)

    import threading as _threading
    t = _threading.Thread(target=_rescan, daemon=True)
    t.start()


def _remove_empty_dirs(
    db: Session,
    old_dirs: list[str],
    folder_paths: list[str],
    journal_id: uuid.UUID,
    items: list[OrganizerJournalItem],
) -> None:
    """Remove directories emptied by the run (Safety rule 8)."""
    folder_keys = {_key(f) for f in folder_paths}
    dirs_to_check = []
    for d in old_dirs:
        current = d
        while True:
            ck = _key(current)
            if ck in folder_keys:
                break
            parent = os.path.dirname(current)
            if not parent or _key(parent) == ck:
                break
            if ck in {_key(p) for p in folder_paths}:
                break
            dirs_to_check.append(current)
            current = parent

    visited = set()
    sort_base = max((i.sort_order for i in items), default=0) + 1
    for d in reversed(dirs_to_check):
        dk = _key(d)
        if dk in visited:
            continue
        visited.add(dk)
        if dk in folder_keys:
            continue
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        if entries:
            continue
        try:
            os.rmdir(d)
            rm_item = OrganizerJournalItem(
                journal_id=journal_id,
                media_file_id=None,
                item_kind="rmdir",
                old_path=d,
                new_path=None,
                sort_order=sort_base,
            )
            db.add(rm_item)
            sort_base += 1
        except OSError as exc:
            log.debug("organizer: could not remove dir %s: %s", d, exc)
    db.flush()


def undo_run(journal_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Reverse a completed apply run."""
    if not _organizer_lock.acquire(blocking=False):
        log.warning("organizer undo: lock already held; aborting")
        return
    try:
        _undo_locked(journal_id, user_id)
    finally:
        _organizer_lock.release()


def _undo_locked(journal_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db = None
    try:
        from app.db import SessionLocal
        db = SessionLocal()
        journal = db.get(OrganizerJournal, journal_id)
        if journal is None:
            return
        if journal.state != "done":
            log.warning("organizer undo: journal %s is in state %s, not done", journal_id, journal.state)
            return

        journal.state = "undoing"
        db.commit()

        settings = library_settings.get_settings(db, journal.library_id) if journal.library_id else {}
        tag_profile = settings.get("tag_profile") or {}
        folder_paths = _get_library_folders(db, journal.library_id) if journal.library_id else []

        items = db.scalars(
            select(OrganizerJournalItem)
            .where(OrganizerJournalItem.journal_id == journal_id)
            .order_by(OrganizerJournalItem.sort_order.desc())
        ).all()

        for item in items:
            if item.error and item.item_kind not in ("sidecar", "rmdir"):
                continue

            if item.item_kind == "rmdir":
                try:
                    os.makedirs(item.old_path, exist_ok=True)
                except OSError as exc:
                    item.error = (item.error or "") + f"; undo_rmdir: {exc}"
                db.commit()
                continue

            if item.item_kind == "sidecar" and item.new_path:
                new_translated = translate_path(item.new_path, db) or item.new_path
                old_translated = translate_path(item.old_path, db) or item.old_path
                if not os.path.exists(new_translated):
                    item.error = (item.error or "") + "; moved_since_apply"
                    db.commit()
                    continue
                if os.path.exists(old_translated) and _key(old_translated) != _key(new_translated):
                    item.error = (item.error or "") + "; old_path_taken"
                    db.commit()
                    continue
                try:
                    os.makedirs(os.path.dirname(old_translated), exist_ok=True)
                    os.rename(new_translated, old_translated)
                except OSError as exc:
                    item.error = (item.error or "") + f"; undo_sidecar: {exc}"
                db.commit()
                continue

            if item.item_kind in ("rename", "both") and item.new_path:
                new_translated = translate_path(item.new_path, db) or item.new_path
                old_translated = translate_path(item.old_path, db) or item.old_path
                if not os.path.exists(new_translated):
                    item.error = "moved_since_apply"
                    db.commit()
                    continue
                if os.path.exists(old_translated) and _key(old_translated) != _key(new_translated):
                    item.error = "old_path_taken"
                    db.commit()
                    continue
                mf = db.get(MediaFile, item.media_file_id) if item.media_file_id else None

                containing_folder = _folder_for_file(new_translated, folder_paths)
                if containing_folder and mf:
                    arr_new_folder = _get_item_folder(new_translated, mf, containing_folder)
                    arr_old_folder = _get_item_folder(old_translated, mf, containing_folder)
                    if arr_new_folder and arr_old_folder and _key(arr_new_folder) != _key(arr_old_folder):
                        err = _update_arr_path(db, mf, arr_old_folder)
                        if err:
                            item.error = f"undo_arr_path_update_failed: {err}"
                            db.commit()
                            continue

                try:
                    os.makedirs(os.path.dirname(old_translated), exist_ok=True)
                    os.rename(new_translated, old_translated)
                except OSError as exc:
                    item.error = str(exc)
                    db.commit()
                    continue

                if mf:
                    mf.path = item.old_path
                    db.flush()

                if containing_folder and mf:
                    _trigger_arr_rescans(db, journal.library_id, [(item.old_path, new_translated, mf.kind, mf.ref_id)])

            if item.item_kind in ("retag", "both") and item.old_tags:
                path_to_tag = translate_path(item.old_path, db) or item.old_path
                old_tags_backup = json.loads(item.old_tags)
                err = tag_writer.restore_tags(path_to_tag, old_tags_backup)
                if err:
                    item.error = (item.error or "") + f"; undo_retag: {err}"

            db.commit()

        journal.state = "undone"
        journal.undo_applied_at = datetime.now(timezone.utc)
        journal.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        log.exception("organizer undo raised: %s", exc)
        if db:
            try:
                j = db.get(OrganizerJournal, journal_id)
                if j:
                    j.state = "failed"
                    j.error = str(exc)
                    db.commit()
            except Exception:
                db.rollback()
    finally:
        if db:
            db.close()


def move_to_recycle(db: Session, media_file_id: uuid.UUID, library_id: uuid.UUID) -> tuple[str, bool]:
    """Move a media file to the library's recycle folder.

    Returns (recycle_path, item_deleted). Raises ValueError when the file is not
    found or not under the library. Deletes the media_file row and its parent item
    when it was the last file.
    """
    from app.models.library import Library

    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise ValueError(f"media_file {media_file_id} not found")

    lib = db.get(Library, library_id)
    if lib is None:
        raise ValueError(f"library {library_id} not found")

    settings = library_settings.get_settings(db, library_id)
    recycle_name = settings.get("recycle_folder", RECYCLE_DIR)

    folder_paths = _get_library_folders(db, library_id)
    translated_path = translate_path(mf.path, db) or mf.path
    containing_folder = _folder_for_file(translated_path, folder_paths)
    if not containing_folder:
        containing_folder = folder_paths[0] if folder_paths else os.path.dirname(translated_path)

    recycle_dir = os.path.join(containing_folder, recycle_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = os.path.basename(translated_path)
    recycle_path = os.path.join(recycle_dir, f"{ts}_{filename}")

    os.makedirs(recycle_dir, exist_ok=True)
    os.rename(translated_path, recycle_path)

    item_deleted = _delete_parent_item_if_last_file(db, mf)
    db.delete(mf)
    db.flush()

    return recycle_path, item_deleted


def _delete_parent_item_if_last_file(db: Session, mf: MediaFile) -> bool:
    """Delete the parent item row when this was the last media_file.

    Returns True when the item was deleted.
    """
    from sqlalchemy import func
    from app.models.media_file import MediaFile as MF

    has_more = db.scalar(
        select(func.count()).select_from(MF).where(
            MF.kind == mf.kind,
            MF.ref_id == mf.ref_id,
            MF.id != mf.id,
        )
    ) or 0
    if has_more > 0:
        return False

    kind = mf.kind
    ref_id = mf.ref_id

    if kind == MediaKind.movie:
        row = db.get(Movie, ref_id)
        if row:
            db.delete(row)
    elif kind == MediaKind.episode:
        ep = db.get(Episode, ref_id)
        if ep:
            db.delete(ep)
    elif kind == MediaKind.track:
        row = db.get(Track, ref_id)
        if row:
            db.delete(row)

    return True


def list_recycle(library_id: uuid.UUID, folder_paths: list[str], recycle_name: str = RECYCLE_DIR) -> list[dict]:
    """List files under the library's recycle folder."""
    results: list[dict] = []
    for folder in folder_paths:
        recycle_dir = os.path.join(folder, recycle_name)
        if not os.path.isdir(recycle_dir):
            continue
        for fname in os.listdir(recycle_dir):
            fpath = os.path.join(recycle_dir, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                results.append({
                    "path": fpath,
                    "filename": fname,
                    "size": stat.st_size,
                })
    return results


def empty_recycle(folder_paths: list[str], recycle_name: str = RECYCLE_DIR) -> int:
    """Permanently delete all files in the recycle folder. Returns count deleted."""
    count = 0
    for folder in folder_paths:
        recycle_dir = os.path.join(folder, recycle_name)
        if not os.path.isdir(recycle_dir):
            continue
        for fname in os.listdir(recycle_dir):
            fpath = os.path.join(recycle_dir, fname)
            if os.path.isfile(fpath):
                try:
                    os.unlink(fpath)
                    count += 1
                except OSError:
                    pass
    return count
