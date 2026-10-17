r"""Server downloads: put an episode in the podcasts library.

A download goes to the first reachable podcasts library folder as
`<folder>\<show>\<YYYY-MM-DD> <title>.<ext>` (the layout the local scan reads),
streams into a `.part` file and is renamed when complete, then gets a
`podcast_episode` media file (ffprobed) and `downloaded_by_f7five0` on the
episode. Names are made safe for Windows: no reserved characters or device
names, no trailing dots or spaces, a bounded length.

Admin can remove a download again, but only a file F7FIVE0 put there itself
and only under the library roots; anything else (a file someone dropped in the
folder) is refused.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.podcast import Podcast, PodcastEpisode
from app.services import library_folders, net_guard
from app.services.path_map import translate as translate_path
from app.services.podcasts import media_types
from app.services.range_response import ensure_under_roots

log = logging.getLogger("f7five0.podcasts.download")

# One episode never needs more than this; a bigger answer is not a podcast.
MAX_EPISODE_BYTES = 4 * 1024 * 1024 * 1024
_CHUNK = 256 * 1024

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Keep the whole path comfortably under Windows MAX_PATH (260).
_PATH_BUDGET = 240


class DownloadError(Exception):
    """A download could not be done. The message is safe to show an admin."""


class NoPodcastFolder(DownloadError):
    """No podcasts library folder is configured, or none can be opened."""


class RemovalRefused(Exception):
    """Admin may not remove this file. `code` is what the API answers."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
def safe_name(raw: object, max_len: int = 100) -> str:
    """A string that is a legal Windows file or folder name: the characters
    Windows forbids become spaces, runs of space collapse, a trailing dot or
    space goes, a device name (CON, NUL.txt, COM1...) gets a leading underscore,
    and it is cut to `max_len`. Never empty."""
    text = unicodedata.normalize("NFC", str(raw or ""))
    text = _ILLEGAL.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(" .")
    if not text:
        return "untitled"
    if text.split(".")[0].upper() in _RESERVED:
        text = "_" + text
    return text[:max_len].rstrip(" .") or "untitled"


def episode_file_name(ep, max_len: int = 120) -> str:
    """`2025-03-01 Episode title.mp3`."""
    when = getattr(ep, "published_at", None) or getattr(ep, "created_at", None)
    prefix = when.strftime("%Y-%m-%d") if when is not None else "0000-00-00"
    ext = media_types.ext_for(getattr(ep, "enclosure_type", None), getattr(ep, "enclosure_url", None))
    stem = safe_name(f"{prefix} {getattr(ep, 'title', '')}", max_len=max(10, max_len - len(ext) - 1))
    return f"{stem}.{ext}"


# ---------------------------------------------------------------------------
# Where
# ---------------------------------------------------------------------------
def configured_folders(db: Session) -> list[str]:
    return library_folders.folders(db, "podcasts")


def first_reachable_folder(db: Session) -> Optional[str]:
    """The first podcasts library folder the server can open now."""
    from app.services import nas_auth
    folders = configured_folders(db)
    if any(nas_auth.is_unc_path(f) for f in folders):
        nas_auth.ensure_all(db)
    for folder in folders:
        if folder and os.path.isdir(folder):
            return folder
    return None


def _free_name(show_dir: str, name: str) -> str:
    """`name`, or `name (2)`... when another file already has it."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(show_dir, candidate)):
        n += 1
        candidate = f"{stem} ({n}){ext}"
    return candidate


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------
def _has_ready_file(db: Session, ep: PodcastEpisode) -> Optional[MediaFile]:
    if not ep.media_file_id:
        return None
    mf = db.get(MediaFile, ep.media_file_id)
    if mf is not None and mf.scan_state == ScanState.ready and os.path.exists(mf.path):
        return mf
    return None


def download_episode(db: Session, ep: PodcastEpisode, *, folder: Optional[str] = None) -> MediaFile:
    """Download one episode into the podcasts library and record it. Does not
    commit. Idempotent: an episode that already has its file returns it."""
    existing = _has_ready_file(db, ep)
    if existing is not None:
        return existing
    if not ep.enclosure_url:
        raise DownloadError("this episode has no audio file to download")
    if media_types.is_video_type(ep.enclosure_type):
        raise DownloadError("video podcasts are not supported yet")
    pod = db.get(Podcast, ep.podcast_id)
    root = folder or first_reachable_folder(db)
    if not root:
        raise NoPodcastFolder("no podcasts folder is set up or reachable")

    show_dir = os.path.join(root, safe_name(pod.title if pod else "podcast", max_len=80))
    created_dir = not os.path.isdir(show_dir)
    budget = max(40, _PATH_BUDGET - len(show_dir) - 1)
    final = os.path.join(show_dir, _free_name(show_dir, episode_file_name(ep, max_len=min(120, budget))))
    part = final + ".part"
    try:
        os.makedirs(show_dir, exist_ok=True)
        _fetch_to(part, ep)
        os.replace(part, final)
    except (OSError, net_guard.NetGuardError) as exc:
        _quiet_remove(part)
        if created_dir:
            _quiet_rmdir(show_dir)
        if isinstance(exc, net_guard.NetGuardError):
            raise DownloadError(f"the publisher could not be reached ({exc})") from None
        raise DownloadError(f"could not write the file ({type(exc).__name__})") from None
    except DownloadError:
        _quiet_remove(part)
        if created_dir:
            _quiet_rmdir(show_dir)
        raise

    from app.services import scan_library  # late: scan_library imports the scheduler

    stored = scan_library._store_path(final)
    mf = scan_library._upsert_file(
        db, kind=MediaKind.podcast_episode, ref_id=ep.id, path=stored,
        stats=scan_library.FolderScanStats(),
    )
    if mf.scan_state != ScanState.ready:
        _quiet_remove(final)
        db.delete(mf)
        db.flush()
        raise DownloadError("the downloaded file could not be read as audio")
    ep.media_file_id = mf.id
    ep.downloaded_by_f7five0 = True
    if not ep.duration_sec and mf.duration_sec:
        ep.duration_sec = mf.duration_sec
    if pod is not None and not pod.folder_path:
        pod.folder_path = show_dir
    db.flush()
    log.info("podcast download: episode %s -> %s (%s bytes)", ep.id, final, mf.size_bytes)
    return mf


def _fetch_to(part_path: str, ep: PodcastEpisode) -> None:
    headers = {"Accept": "audio/*, */*;q=0.5", "Accept-Encoding": "identity"}
    with net_guard.open_stream(ep.enclosure_url or "", headers=headers) as stream:
        resp = stream.response
        if resp.status_code != 200:
            raise DownloadError(f"the publisher answered HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type")
        if not (media_types.is_audio_response(ctype, stream.url)
                or media_types.is_audio_response(ctype, ep.enclosure_url)):
            raise DownloadError("the publisher did not send audio")
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_EPISODE_BYTES:
            raise DownloadError("the file is larger than the 4 GB limit")
        written = 0
        with open(part_path, "wb") as fh:
            try:
                for chunk in resp.iter_bytes(_CHUNK):
                    written += len(chunk)
                    if written > MAX_EPISODE_BYTES:
                        raise DownloadError("the file is larger than the 4 GB limit")
                    fh.write(chunk)
            except net_guard.httpx.HTTPError as exc:
                raise DownloadError(f"the download was interrupted ({type(exc).__name__})") from None
        if written == 0:
            raise DownloadError("the publisher sent an empty file")


def _quiet_remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        log.warning("could not remove %s", path, exc_info=True)


def _quiet_rmdir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Removing a download (Admin)
# ---------------------------------------------------------------------------
def _roots(db: Session) -> list[Path]:
    roots: list[Path] = []
    for folder in configured_folders(db):
        if not folder:
            continue
        roots.append(Path(folder))
        translated = translate_path(folder, db)
        if translated and translated != folder:
            roots.append(Path(translated))
    return roots


def delete_download(db: Session, ep: PodcastEpisode) -> None:
    """Remove the file F7FIVE0 downloaded for this episode. Refuses (RemovalRefused)
    anything else: no file, a file somebody else put there, or a path outside the
    podcasts library folders. Does not commit."""
    if not ep.downloaded_by_f7five0 or not ep.media_file_id:
        raise RemovalRefused("not_downloaded_by_f7five0")
    mf = db.get(MediaFile, ep.media_file_id)
    if mf is None:
        raise RemovalRefused("not_downloaded_by_f7five0")
    path = Path(mf.path)
    try:
        ensure_under_roots(path, _roots(db))
    except HTTPException:
        raise RemovalRefused("outside_library_roots") from None
    _quiet_remove(str(path))
    _quiet_rmdir(str(path.parent))
    ep.media_file_id = None
    ep.downloaded_by_f7five0 = False
    db.flush()
    db.delete(mf)
    db.flush()
    log.info("podcast download removed: episode %s (%s)", ep.id, path)
