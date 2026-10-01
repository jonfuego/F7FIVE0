r"""Filesystem scanner for music videos.

Music videos are filesystem-derived; *arr apps don't manage them. Folder
contract:

    <root>\<Artist>\<Release>\<Title>.<ext>                 single-disc
    <root>\<Artist>\<Release>\Disc NN\<Title>.<ext>         multi-disc

Multi-disc releases are detected by a `Disc NN` (or `CD NN`, `DVD NN`,
`BD NN`) folder one level below the release. Anything else (`Bonus`,
`Behind The Scenes`, `Extras`) folds into disc 1 with the deeper relative
path preserved on the video.

Loose top-level files directly under the artist (no enclosing release
folder) are skipped with a warning. Keep the folder layout to the contract.

Paths are translated through `path_map.translate()` so the stored value
is always a UNC the service account can resolve. Missing-file handling
mirrors the *arr sync: rows that previously pointed at a file we no
longer see get `scan_state` flipped to `missing`.

Cover sidecars: `cover.{jpg,jpeg,png,webp}` or `folder.{jpg,jpeg,png,webp}`
at the release-folder root populate `release.cover_path`. Per-video
`thumb_path` continues to look for `<stem>.{jpg,...}` next to each file.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Artist, MusicVideo, MusicVideoRelease
from app.services import ffprobe
from app.services.path_map import translate as translate_path


log = logging.getLogger("f7five0.scan_music_videos")


# Video containers we'll consider. Keep the list narrow so stray files
# (images, playlists, .nfo) don't trip the walker.
_VIDEO_EXTS = {"mp4", "mkv", "webm", "mov", "m4v", "avi", "wmv"}

# Sidecar image extensions for a per-video thumbnail, checked in order.
_THUMB_EXTS = ("jpg", "jpeg", "png", "webp")

# Release-level cover sidecars, checked in order.
_COVER_STEMS = ("cover", "folder")
_COVER_EXTS = ("jpg", "jpeg", "png", "webp")

# Matches `Disc 01`, `Disc 1`, `CD1`, `CD 02`, `DVD 1`, `BD 02`, etc.
_DISC_RE = re.compile(r"^(disc|cd|dvd|bd)[\s_-]*0*(\d+)$", re.IGNORECASE)

# Leading track number on a filename: "01 - Title", "1. Title", "1_Title",
# "01-Title". Captures the integer.
_TRACK_RE = re.compile(r"^(\d+)\s*[-._\s]\s*")

# Year in a release title: prefer the LAST 19xx/20xx token so
# "Best Of 1980-1985" picks 1985 rather than 1980.
_YEAR_RE = re.compile(r"(?:^|\s)(19\d{2}|20\d{2})(?:\s|$)")


@dataclass
class ScanStats:
    artists_upserted: int = 0
    releases_upserted: int = 0
    videos_upserted: int = 0
    files_upserted: int = 0
    files_probed: int = 0
    files_missing: int = 0
    errors: int = 0

    def log_summary(self) -> None:
        log.info(
            "music_videos scan complete: artists=%d releases=%d videos=%d "
            "files=%d probed=%d missing=%d errors=%d",
            self.artists_upserted, self.releases_upserted,
            self.videos_upserted, self.files_upserted,
            self.files_probed, self.files_missing, self.errors,
        )


# ---------------------------------------------------------------------------
# Pure helpers (no DB)
# ---------------------------------------------------------------------------
def parse_disc_folder(name: str) -> Optional[int]:
    """Return the disc number for a folder name like `Disc 01`, or None."""
    m = _DISC_RE.match(name.strip())
    if not m:
        return None
    try:
        return int(m.group(2))
    except ValueError:
        return None


def parse_track_number(filename: str) -> Optional[int]:
    """Pull a leading track number off a filename. `01 - Title.mp4` → 1."""
    stem = os.path.splitext(filename)[0]
    m = _TRACK_RE.match(stem)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def parse_release_year(title: str) -> Optional[int]:
    """Last 19xx/20xx token in a release title, or None."""
    matches = _YEAR_RE.findall(title)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def find_release_cover(release_dir: str) -> Optional[str]:
    """Look for cover.{jpg,...} or folder.{jpg,...} at the release root."""
    for stem in _COVER_STEMS:
        for ext in _COVER_EXTS:
            candidate = os.path.join(release_dir, f"{stem}.{ext}")
            if os.path.isfile(candidate):
                return candidate
    return None


def _find_sidecar_thumb(folder: str, stem: str) -> Optional[str]:
    for ext in _THUMB_EXTS:
        candidate = os.path.join(folder, f"{stem}.{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass
class DiscoveredVideo:
    """One video found under a release folder. Pure data; no DB types."""
    title: str
    source_subpath: str            # POSIX path under the release folder
    disc_number: int
    track_number: Optional[int]
    abs_path: str                  # filesystem path before path_map translate
    thumb_path: Optional[str]


@dataclass
class DiscoveredRelease:
    """One release folder under an artist. Children listed in scan order."""
    title: str                     # the release folder's name verbatim
    source_subpath: str            # POSIX path under the artist folder
    cover_path: Optional[str]
    release_year: Optional[int]
    videos: list[DiscoveredVideo] = field(default_factory=list)


def discover_release(release_dir: str) -> DiscoveredRelease:
    """Walk a release folder and return its videos.

    Videos sit either directly under the release folder (single-disc
    implicit) or under a disc subfolder. Anything that isn't a disc folder
    folds into disc 1 with the deeper path preserved.
    """
    release_name = os.path.basename(os.path.normpath(release_dir))
    rel = DiscoveredRelease(
        title=release_name,
        source_subpath=release_name,
        cover_path=find_release_cover(release_dir),
        release_year=parse_release_year(release_name),
    )
    for dirpath, _dirnames, filenames in os.walk(release_dir):
        # Disc detection: look at the path components relative to the
        # release directory. The first component matching the disc regex
        # sets the disc number; deeper paths are preserved on the video.
        rel_dir = os.path.relpath(dirpath, release_dir).replace("\\", "/")
        disc = 1
        if rel_dir != ".":
            first = rel_dir.split("/", 1)[0]
            parsed = parse_disc_folder(first)
            if parsed is not None:
                disc = parsed
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lstrip(".").lower()
            if ext not in _VIDEO_EXTS:
                continue
            stem = os.path.splitext(fname)[0].strip()
            if not stem:
                continue
            abs_path = os.path.join(dirpath, fname)
            subpath_under_release = os.path.relpath(
                abs_path, release_dir
            ).replace("\\", "/")
            # Strip the disc-folder segment from the stored subpath so
            # disc info lives only on disc_number. Deeper subfolders
            # (Bonus, etc.) inside disc 1 keep their relative path.
            if rel_dir != ".":
                first = rel_dir.split("/", 1)[0]
                if parse_disc_folder(first) is not None:
                    parts = subpath_under_release.split("/", 1)
                    subpath_under_release = parts[1] if len(parts) > 1 else stem
            track = parse_track_number(fname)
            thumb = _find_sidecar_thumb(dirpath, os.path.splitext(fname)[0])
            rel.videos.append(DiscoveredVideo(
                title=stem,
                source_subpath=subpath_under_release,
                disc_number=disc,
                track_number=track,
                abs_path=abs_path,
                thumb_path=thumb,
            ))
    return rel


def discover_artist(artist_dir: str) -> Iterator[DiscoveredRelease]:
    """Yield one DiscoveredRelease per immediate subfolder of an artist."""
    try:
        entries = sorted(os.listdir(artist_dir))
    except OSError:
        log.exception("failed to list artist folder %s", artist_dir)
        return
    for entry in entries:
        full = os.path.join(artist_dir, entry)
        if not os.path.isdir(full):
            # Loose file directly under the artist. Folder contract says
            # there shouldn't be any; warn and skip rather than auto-bucket.
            ext = os.path.splitext(entry)[1].lstrip(".").lower()
            if ext in _VIDEO_EXTS:
                log.warning(
                    "loose music-video file under artist (no release folder); "
                    "skipping: %s", full,
                )
            continue
        yield discover_release(full)


# ---------------------------------------------------------------------------
# Scan entry point (DB)
# ---------------------------------------------------------------------------
def scan(db: Session) -> ScanStats:
    """Walk the music-videos root and reconcile DB state with disk."""
    stats = ScanStats()
    root = str(settings.library_root_music_videos)
    if not root:
        log.warning("library_root_music_videos is empty; skipping scan")
        return stats
    if not os.path.isdir(root):
        log.warning("music videos root not found: %s", root)
        return stats

    seen_paths: set[str] = set()

    try:
        artist_entries = sorted(os.listdir(root))
    except OSError:
        log.exception("failed to list music videos root %s", root)
        stats.errors += 1
        return stats

    for artist_dir in artist_entries:
        artist_path = os.path.join(root, artist_dir)
        if not os.path.isdir(artist_path):
            continue
        artist_name = artist_dir.strip()
        if not artist_name:
            continue

        artist = _upsert_artist(db, artist_name, stats)

        for disc in discover_artist(artist_path):
            release = _upsert_release(db, artist, disc, stats)
            for v in disc.videos:
                mv = _upsert_music_video(db, artist, release, v, stats)
                stored_path = translate_path(v.abs_path) or v.abs_path
                seen_paths.add(stored_path)
                _upsert_media_file(db, mv, stored_path, stats)

    _mark_missing(db, seen_paths, stats)
    stats.log_summary()
    return stats


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------
def _upsert_artist(db: Session, name: str, stats: ScanStats) -> Artist:
    artist = db.scalar(
        select(Artist).where(func.lower(Artist.name) == name.lower())
    )
    if artist is None:
        artist = Artist(name=name)
        db.add(artist)
        db.flush()
        stats.artists_upserted += 1
    return artist


def _upsert_release(
    db: Session,
    artist: Artist,
    disc: DiscoveredRelease,
    stats: ScanStats,
) -> MusicVideoRelease:
    release = db.scalar(
        select(MusicVideoRelease).where(
            MusicVideoRelease.artist_id == artist.id,
            MusicVideoRelease.source_subpath == disc.source_subpath,
        )
    )
    if release is None:
        release = MusicVideoRelease(
            artist_id=artist.id,
            title=disc.title,
            source_subpath=disc.source_subpath,
            release_year=disc.release_year,
            cover_path=disc.cover_path,
        )
        db.add(release)
        db.flush()
        stats.releases_upserted += 1
    else:
        if release.title != disc.title:
            release.title = disc.title
        if disc.cover_path and release.cover_path != disc.cover_path:
            release.cover_path = disc.cover_path
        if disc.release_year and release.release_year != disc.release_year:
            release.release_year = disc.release_year
    return release


def _upsert_music_video(
    db: Session,
    artist: Artist,
    release: MusicVideoRelease,
    v: DiscoveredVideo,
    stats: ScanStats,
) -> MusicVideo:
    mv = db.scalar(
        select(MusicVideo).where(
            MusicVideo.release_id == release.id,
            MusicVideo.source_subpath == v.source_subpath,
        )
    )
    if mv is None:
        mv = MusicVideo(
            release_id=release.id,
            artist_id=artist.id,
            title=v.title,
            source_subpath=v.source_subpath,
            disc_number=v.disc_number,
            track_number=v.track_number,
            thumb_path=v.thumb_path,
        )
        db.add(mv)
        db.flush()
        stats.videos_upserted += 1
    else:
        if mv.title != v.title:
            mv.title = v.title
        if mv.disc_number != v.disc_number:
            mv.disc_number = v.disc_number
        if mv.track_number != v.track_number:
            mv.track_number = v.track_number
        if v.thumb_path and mv.thumb_path != v.thumb_path:
            mv.thumb_path = v.thumb_path
    return mv


def _upsert_media_file(
    db: Session, mv: MusicVideo, path: str, stats: ScanStats,
) -> MediaFile:
    existing = db.scalar(select(MediaFile).where(MediaFile.path == path))
    if existing is None:
        mf = MediaFile(kind=MediaKind.music_video, ref_id=mv.id, path=path)
        db.add(mf)
    else:
        mf = existing
        mf.kind = MediaKind.music_video
        mf.ref_id = mv.id

    if not mf.container:
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        mf.container = ext or None

    try:
        if os.path.exists(path):
            mf.size_bytes = os.path.getsize(path) or mf.size_bytes
    except OSError:
        pass

    db.flush()
    stats.files_upserted += 1

    if mf.scan_state != ScanState.ready or mf.probed_at is None:
        _probe(db, mf, stats)
    return mf


def _probe(db: Session, mf: MediaFile, stats: ScanStats) -> None:
    result = ffprobe.probe(mf.path)
    if result is None:
        if not os.path.exists(mf.path):
            mf.scan_state = ScanState.missing
            stats.files_missing += 1
        else:
            mf.scan_state = ScanState.error
            stats.errors += 1
        return
    mf.container = result.container or mf.container
    mf.size_bytes = result.size_bytes or mf.size_bytes
    mf.duration_sec = result.duration_sec or mf.duration_sec
    mf.bitrate_kbps = result.bitrate_kbps or mf.bitrate_kbps
    mf.video_codec = result.video_codec or mf.video_codec
    mf.audio_codec = result.audio_codec or mf.audio_codec
    mf.audio_channels = result.audio_channels or mf.audio_channels
    mf.width = result.width or mf.width
    mf.height = result.height or mf.height
    mf.probed_at = datetime.now(timezone.utc)
    mf.scan_state = ScanState.ready
    stats.files_probed += 1


def _mark_missing(
    db: Session, seen_paths: Iterable[str], stats: ScanStats,
) -> None:
    seen = set(seen_paths)
    rows = db.scalars(
        select(MediaFile).where(MediaFile.kind == MediaKind.music_video)
    ).all()
    for mf in rows:
        if mf.path not in seen and mf.scan_state != ScanState.missing:
            mf.scan_state = ScanState.missing
            stats.files_missing += 1
