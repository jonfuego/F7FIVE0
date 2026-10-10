r"""Folder scanner for movies, TV, and music.

This is the no-*arr path. When a library has one or more source folders
(app/services/library_folders.py: Admin > Library folders, or LIBRARY_ROOT_*
in .env) and the matching *arr API key is blank, F7FIVE0 builds that library
straight from the files on disk. When the *arr key is set, the *arr sync owns the library
and this scanner leaves it alone, so the two never fight over the same rows.

Folder conventions (the same ones Plex, Jellyfin, and the *arr apps use):

    Movies  <root>\Title (Year)\Title (Year).mkv
            <root>\Title (Year).mkv                       loose files work too
            An optional `{tmdb-12345}` tag in the folder or file name pins
            the TMDB match.

    TV      <root>\Show Name (Year)\Season 01\Show Name - S01E02 - Title.mkv
            `S01E02`, `s1e2`, and `1x02` episode tokens are recognized.
            `Specials` maps to season 0.

    Music   <root>\Artist\Album\01 - Title.flac
            Embedded tags win when present (artist, album artist, album,
            title, track, disc, year, MusicBrainz ids). Folder and file
            names are the fallback.

Art: `poster.*` / `folder.*` / `cover.*` and `fanart.*` / `backdrop.*`
sidecars are imported into the local art cache. Music falls back to the
cover embedded in the first track. When a TMDB API key is configured,
movies and shows without a TMDB id are matched by title and year, and
posters/backdrops are fetched for anything that has no local sidecar.
Admin-picked art is never overwritten.

Rescans are incremental: a file already `ready` with the same size is not
re-probed. Files that disappear are flipped to `missing`, never deleted, so
watch history survives a drive that is briefly offline. A folder that can't
be opened at all is skipped for that pass and its files are left as they are.

Several folders per library: TV and music merge across folders (one show,
one artist, one album). Movies do not: the same movie found in two folders
shows as two entries (decision 2026-10-03). The second entry can't share the
TMDB id (unique), so it copies the details and art of the first.

Saving as it goes: a scan commits every BATCH_SIZE items and at the end of
each library, so rows show up in the app while the scan runs and a scan that
stops part way keeps what it saved. Enrichment jobs (TMDB / MusicBrainz) are
scheduled only after the batch that holds their row has committed; scheduled
earlier they would run in their own session, not find the row, and never be
retried. After a pass, `schedule_catch_up` re-queues rows that were missed.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Iterable, Iterator, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scheduler
from app.config import settings
from app.models.art import (
    ArtOverride, ENTITY_ALBUM, ENTITY_ARTIST, ENTITY_MOVIE, ENTITY_SERIES,
    ROLE_BACKDROP, ROLE_COVER, ROLE_POSTER, ROLE_THUMB,
)
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.tv import Episode, Season, Series
from app.services import ffprobe, library_folders, tmdb_key
from app.services.path_map import translate as translate_path


log = logging.getLogger("f7five0.scan_library")

SOURCE_LOCAL = "local"
SOURCE_TMDB = "tmdb"
# Art rows this scanner may refresh. Anything else (upload, url, *arr,
# fanart, musicbrainz) belongs to someone else and is left alone.
_SCANNER_SOURCES = frozenset({SOURCE_LOCAL, SOURCE_TMDB})

VIDEO_EXTS = {"mkv", "mp4", "m4v", "avi", "mov", "webm", "ts", "m2ts", "wmv", "mpg", "mpeg"}
AUDIO_EXTS = {"flac", "mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "wma", "alac", "aiff", "aif", "ape", "wv"}
_IMAGE_EXTS = ("jpg", "jpeg", "png", "webp")

# Folders that hold bonus material, not the feature itself.
_SKIP_DIRS = {
    "extras", "featurettes", "behind the scenes", "deleted scenes",
    "interviews", "scenes", "shorts", "trailers", "other", "sample",
    "samples", "subs", "subtitles", "@eadir", "#recycle", "$recycle.bin",
    ".trash", ".actors", "metadata",
}

_TMDB_TAG_RE = re.compile(r"[\[{]\s*tmdb(?:id)?[-=\s]*(\d+)\s*[\]}]", re.IGNORECASE)
_BRACKETS_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_YEAR_PAREN_RE = re.compile(r"\((19\d{2}|20\d{2})\)")
_YEAR_BARE_RE = re.compile(r"(?:^|[\s._\-])(19\d{2}|20\d{2})(?=$|[\s._\-])")
# Release-name junk after the title in scene-style names.
_JUNK_RE = re.compile(
    r"[\s._\-](2160p|1080p|1080i|720p|576p|480p|4k|uhd|bluray|blu-ray|bdrip|brrip|"
    r"web-?dl|webrip|web|hdtv|dvdrip|dvd|remux|hdr|hdr10|dv|x264|x265|h\.?264|h\.?265|"
    r"hevc|avc|aac|ac3|dts|atmos|truehd|proper|repack|extended|unrated|imax|"
    r"directors\.cut|remastered)(?=$|[\s._\-])",
    re.IGNORECASE,
)
_EPISODE_RE = re.compile(r"[Ss](\d{1,3})[\s._\-]*[Ee](\d{1,4})")
_EPISODE_X_RE = re.compile(r"(?:^|[\s._\-])(\d{1,2})x(\d{1,3})(?=$|[\s._\-])")
_SEASON_DIR_RE = re.compile(r"^(?:season|series|staffel|saison|temporada)[\s._\-]*(\d{1,3})$", re.IGNORECASE)
_TRACK_PREFIX_RE = re.compile(r"^(?:(\d{1,2})[-.])?(\d{1,3})\s*[-._\s]\s*")
_DISC_DIR_RE = re.compile(r"^(?:disc|disk|cd)[\s._\-]*0*(\d+)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@dataclass
class FolderScanStats:
    movies: int = 0
    series: int = 0
    episodes: int = 0
    artists: int = 0
    albums: int = 0
    tracks: int = 0
    files_seen: int = 0
    files_probed: int = 0
    files_missing: int = 0
    art_imported: int = 0
    errors: int = 0
    # A short one-line reason for the most recent per-file error (file path plus
    # a one-line cause), safe to show an admin. Never the raw SQL dump.
    last_error: Optional[str] = None

    def log_summary(self, label: str) -> None:
        log.info(
            "%s folder scan: movies=%d series=%d eps=%d artists=%d albums=%d "
            "tracks=%d files=%d probed=%d missing=%d art=%d errors=%d",
            label, self.movies, self.series, self.episodes, self.artists,
            self.albums, self.tracks, self.files_seen, self.files_probed,
            self.files_missing, self.art_imported, self.errors,
        )


# ---------------------------------------------------------------------------
# Which libraries does this scanner own?
# ---------------------------------------------------------------------------
def movies_enabled(db: Optional[Session] = None) -> bool:
    return bool(library_folders.folders(db, "movies")) and not settings.radarr_api_key


def tv_enabled(db: Optional[Session] = None) -> bool:
    return bool(library_folders.folders(db, "tv")) and not settings.sonarr_api_key


def music_enabled(db: Optional[Session] = None) -> bool:
    return bool(library_folders.folders(db, "music")) and not settings.lidarr_api_key


def any_enabled(db: Optional[Session] = None) -> bool:
    return movies_enabled(db) or tv_enabled(db) or music_enabled(db)


# Items (a movie, an episode, a track: whatever the loop counts) per commit.
BATCH_SIZE = 25

# Pause between catch-up enrichment jobs, on top of the usual per-item delay,
# so re-queuing a big library does not hit TMDB / MusicBrainz all at once.
CATCH_UP_STAGGER_SEC = 1.0

# on_progress(label, state, stats, error): the scan reports each library as it
# starts, at every batch commit (state "running"), and when it ends ("done" or
# "failed", with the error text). Admin's scan status is built from this.
ProgressFn = Callable[..., None]


class _Batcher:
    """Commits a library's scan every BATCH_SIZE items and at its end, and
    holds enrichment jobs back until the rows they belong to are committed."""

    def __init__(self, db: Session, label: str, stats: "FolderScanStats", on_progress: Optional[ProgressFn] = None) -> None:
        self.db = db
        self.label = label
        self.stats = stats
        self.on_progress = on_progress
        self._items = 0
        self._movies: list = []
        self._artists: list = []
        self._albums: list = []

    def enrich_movie(self, movie_id) -> None:
        self._movies.append(movie_id)

    def enrich_artist(self, artist_id) -> None:
        self._artists.append(artist_id)

    def enrich_album(self, album_id) -> None:
        self._albums.append(album_id)

    def item_done(self) -> None:
        self._items += 1
        if self._items >= BATCH_SIZE:
            self.commit()

    def commit(self) -> None:
        """Save everything so far (rows and scan status together), then queue
        enrichment for the rows that save made visible."""
        if self.on_progress is not None:
            self.on_progress(self.label, "running", self.stats, self.stats.last_error)
        self.db.commit()
        self._items = 0
        movies, artists, albums = self._movies, self._artists, self._albums
        self._movies, self._artists, self._albums = [], [], []
        for ids, schedule in (
            (movies, scheduler.schedule_enrich_movie),
            (artists, scheduler.schedule_enrich_artist),
            (albums, scheduler.schedule_enrich_album),
        ):
            for item_id in ids:
                try:
                    schedule(item_id)
                except Exception:
                    log.exception("could not schedule enrichment for %s", item_id)


def scan_all(db: Session, on_progress: Optional[ProgressFn] = None) -> FolderScanStats:
    """Scan every library this scanner owns, saving as it goes.

    Each library commits every BATCH_SIZE items and at its end. A library that
    raises loses only the batch it was in: what it committed earlier stays, a
    rollback drops the rest, and the other libraries still run."""
    total = FolderScanStats()
    for label, enabled, fn in (
        ("movies", movies_enabled, scan_movies),
        ("tv", tv_enabled, scan_tv),
        ("music", music_enabled, scan_music),
    ):
        if not enabled(db):
            continue
        stats = FolderScanStats()
        if on_progress is not None:
            on_progress(label, "running", stats)
            db.commit()  # Admin shows "scanning" before the first batch is done
        error = None
        try:
            fn(db, stats, on_progress)
        except Exception as exc:
            log.exception("%s folder scan failed", label)
            db.rollback()
            stats.errors += 1
            error = f"{label} scan failed: {exc}"
        # A library that raised is "failed"; one that finished but skipped bad
        # files is "done" with an error count and the last per-file reason.
        if on_progress is not None:
            on_progress(label, "failed" if error else "done", stats, error or stats.last_error)
        db.commit()
        for k in total.__dataclass_fields__:
            if k == "last_error":
                total.last_error = stats.last_error or total.last_error
                continue
            setattr(total, k, getattr(total, k) + getattr(stats, k))
    return total


def schedule_catch_up(db: Session) -> dict:
    """Queue enrichment for rows that have a TMDB / MusicBrainz id but were
    never enriched (`metadata_synced_at` is null). This repairs installs whose
    first scan lost its enrichment jobs, and it is cheap to run after every
    scan: enrichment stamps `metadata_synced_at` even when it fails, so a row
    is queued once, not forever. Jobs keep their `replace_existing` ids and
    are spaced out so a big library cannot flood the API. Movies are left
    alone while no TMDB key is set (a run without one would only mark them
    done). Call it after the scan's commit."""
    movie_ids = []
    if tmdb_key.get():
        movie_ids = list(db.scalars(select(Movie.id).where(
            Movie.tmdb_id.is_not(None), Movie.metadata_synced_at.is_(None),
        )))
    artist_ids = list(db.scalars(select(Artist.id).where(
        Artist.mbid.is_not(None), Artist.metadata_synced_at.is_(None),
    )))
    album_ids = list(db.scalars(select(Album.id).where(
        Album.mbid.is_not(None), Album.metadata_synced_at.is_(None),
    )))
    n = 0
    for ids, schedule in (
        (movie_ids, scheduler.schedule_enrich_movie),
        (artist_ids, scheduler.schedule_enrich_artist),
        (album_ids, scheduler.schedule_enrich_album),
    ):
        for item_id in ids:
            schedule(item_id, delay_sec=scheduler.ENRICH_DELAY_SEC + n * CATCH_UP_STAGGER_SEC)
            n += 1
    if n:
        log.info("enrichment catch-up: %d movies, %d artists, %d albums queued",
                 len(movie_ids), len(artist_ids), len(album_ids))
    return {"movies": len(movie_ids), "artists": len(artist_ids), "albums": len(album_ids)}


# ---------------------------------------------------------------------------
# Pure parsing helpers (unit tested)
# ---------------------------------------------------------------------------
def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lstrip(".").lower()


def _clean_spaces(value: str) -> str:
    value = re.sub(r"[._]+", " ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip(" -_.")


def parse_tmdb_tag(name: str) -> Optional[int]:
    m = _TMDB_TAG_RE.search(name)
    return int(m.group(1)) if m else None


def parse_title_year(name: str) -> tuple[str, Optional[int]]:
    """`The Matrix (1999) [1080p]` -> ("The Matrix", 1999).
    `The.Matrix.1999.1080p.BluRay` -> ("The Matrix", 1999)."""
    stem = _BRACKETS_RE.sub(" ", name)
    m = _YEAR_PAREN_RE.search(stem)
    if m:
        title = stem[: m.start()]
        return _clean_spaces(title) or _clean_spaces(stem), int(m.group(1))
    # Scene style: cut at the last bare year that is not the whole title.
    years = list(_YEAR_BARE_RE.finditer(stem))
    for ym in reversed(years):
        title = stem[: ym.start()]
        if _clean_spaces(title):
            return _clean_spaces(title), int(ym.group(1))
    j = _JUNK_RE.search(stem)
    if j and _clean_spaces(stem[: j.start()]):
        stem = stem[: j.start()]
    return _clean_spaces(stem), None


def _show_title_year(show_name: str) -> tuple[str, Optional[int]]:
    """Show title and year from a top-level TV folder name.

    Scene-style folders carry an episode code in the folder name itself
    (`Smallville S04E02`, `Smallville.S04E04.1080p.WEB-DL`). Left alone each
    one becomes its own single-episode show. Cut the name at the episode code
    and parse the text before it, so every episode of a show groups under one
    series."""
    m = _EPISODE_RE.search(show_name) or _EPISODE_X_RE.search(show_name)
    base = show_name[: m.start()] if m else show_name
    title, year = parse_title_year(base)
    return title or _clean_spaces(base) or show_name, year


def parse_episode(filename: str) -> Optional[tuple[int, int, Optional[str]]]:
    """Return (season, episode, title-or-None) from an episode file name."""
    stem = os.path.splitext(filename)[0]
    m = _EPISODE_RE.search(stem) or _EPISODE_X_RE.search(stem)
    if not m:
        return None
    season, episode = int(m.group(1)), int(m.group(2))
    rest = stem[m.end():]
    # Skip chained episode tokens like E02E03 / -E03.
    rest = re.sub(r"^([\s._\-]*[Ee]\d{1,4})+", "", rest)
    j = _JUNK_RE.search(rest)
    if j:
        rest = rest[: j.start()]
    title = _clean_spaces(_BRACKETS_RE.sub(" ", rest)) or None
    return season, episode, title


def parse_season_dir(name: str) -> Optional[int]:
    if name.strip().lower() in ("specials", "special", "season 0", "extras s00"):
        return 0
    m = _SEASON_DIR_RE.match(name.strip())
    return int(m.group(1)) if m else None


def parse_track_filename(filename: str) -> tuple[Optional[int], Optional[int], str]:
    """`01 - Title.flac` -> (None, 1, "Title"); `2-05 Title.mp3` -> (2, 5, "Title")."""
    stem = os.path.splitext(filename)[0]
    m = _TRACK_PREFIX_RE.match(stem)
    if not m:
        return None, None, _clean_spaces(stem) or stem
    disc = int(m.group(1)) if m.group(1) else None
    return disc, int(m.group(2)), (stem[m.end():].strip() or stem)


def _num(value) -> Optional[int]:
    """Tag numbers arrive as '3', '3/12', ['3'], or ints."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, int):
        return value
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def _first(tags: dict, *keys: str) -> Optional[str]:
    for k in keys:
        v = tags.get(k)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


# One MusicBrainz id tag can hold several ids joined by whitespace, "/", ";",
# or "," (a collaboration track lists every credited artist). Artist.mbid and
# the other mbid columns are String(64); a joined pair is 73 chars and used to
# make the whole scan fail. Keep the first token that is a real UUID.
_MBID_SPLIT_RE = re.compile(r"[\s/;,]+")


def normalize_mbid(value) -> Optional[str]:
    """Return the first valid MusicBrainz UUID in a tag value, else None.

    Accepts a string, a list/tuple (first element), or None. Splits on
    whitespace, "/", ";", and "," and keeps the first token that parses as a
    UUID, so a tag with two ids joined together stores one id, not both."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    for token in _MBID_SPLIT_RE.split(str(value).strip()):
        if not token:
            continue
        try:
            return str(uuid.UUID(token))
        except ValueError:
            continue
    return None


def _short_reason(exc: Exception) -> str:
    """A one-line, admin-safe cause from an exception. Never the raw SQL dump:
    an SQLAlchemy error carries the full statement and parameters, which leaks
    "INSERT INTO ...", column truncation internals and the like. Take the DB
    driver's own short message when there is one, else the exception type."""
    orig = getattr(exc, "orig", None)
    if orig is not None:
        text = str(orig).strip().splitlines()[0] if str(orig).strip() else ""
    else:
        text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    low = text.lower()
    if not text or "insert into" in low or "update " in low or "sqlalchemy" in low or "[sql:" in low:
        text = type(exc).__name__
    return text[:200]


def _record_file_error(path: str, exc: Exception, stats: FolderScanStats) -> None:
    """Note one file's failure without leaking the SQL dump. Full detail goes to
    the API log; the admin-facing status gets the file path and a short reason."""
    reason = _short_reason(exc)
    log.exception("skipping music file after an error: %s", path)
    stats.errors += 1
    stats.last_error = f"{path}: {reason}"


def _is_skip_dir(name: str) -> bool:
    n = name.strip().lower()
    return n in _SKIP_DIRS or n.startswith(".")


def _is_sample(filename: str) -> bool:
    stem = os.path.splitext(filename)[0].lower()
    return stem == "sample" or stem.endswith(("-sample", ".sample", " sample")) or stem.endswith(("-trailer", ".trailer"))


def _find_sidecar(folder: str, stems: Iterable[str]) -> Optional[str]:
    try:
        names = {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return None
    for stem in stems:
        for ext in _IMAGE_EXTS:
            hit = names.get(f"{stem}.{ext}")
            if hit:
                return os.path.join(folder, hit)
    return None


# ---------------------------------------------------------------------------
# Shared DB helpers
# ---------------------------------------------------------------------------
def _mtime(path: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except OSError:
        return None


def _existing_ref(db: Session, path: str, kind: MediaKind):
    mf = db.scalar(select(MediaFile).where(MediaFile.path == path))
    if mf is not None and mf.kind == kind:
        return mf.ref_id
    return None


def _upsert_file(db: Session, *, kind: MediaKind, ref_id, path: str, stats: FolderScanStats) -> MediaFile:
    mf = db.scalar(select(MediaFile).where(MediaFile.path == path))
    try:
        size = os.path.getsize(path)
    except OSError:
        size = None
    if mf is None:
        mf = MediaFile(kind=kind, ref_id=ref_id, path=path)
        db.add(mf)
    else:
        mf.kind = kind
        mf.ref_id = ref_id
    if not mf.container:
        mf.container = _ext(path) or None
    changed = size is not None and mf.size_bytes != size
    if size is not None:
        mf.size_bytes = size
    db.flush()
    stats.files_seen += 1
    if changed or mf.scan_state != ScanState.ready or mf.probed_at is None:
        _probe(mf, stats)
    return mf


def _probe(mf: MediaFile, stats: FolderScanStats) -> None:
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


def _mark_missing_under(db: Session, kind: MediaKind, root: str, seen: set[str], stats: FolderScanStats) -> None:
    """Flip rows under `root` that were not seen this pass to `missing`."""
    prefix = (translate_path(root) or root).rstrip("\\/")
    rows = db.scalars(select(MediaFile).where(MediaFile.kind == kind)).all()
    for mf in rows:
        p = mf.path or ""
        if not (p == prefix or p.startswith(prefix + os.sep) or p.startswith(prefix + "/") or p.startswith(prefix + "\\")):
            continue
        if p not in seen and mf.scan_state != ScanState.missing:
            mf.scan_state = ScanState.missing
            stats.files_missing += 1


def _store_path(path: str) -> str:
    return translate_path(path) or path


def _reachable(roots: list[str], label: str) -> list[tuple[int, str]]:
    """(index, folder) for every configured folder that can be opened now.
    The others are skipped this pass; their rows are left alone."""
    out: list[tuple[int, str]] = []
    for i, root in enumerate(roots):
        if root and os.path.isdir(root):
            out.append((i, root))
        else:
            log.warning("%s folder not found, skipped this pass: %r", label, root)
    return out


def _root_prefixes(roots: list[str]) -> list[str]:
    return [os.path.normcase(_store_path(r).rstrip("\\/")) for r in roots]


def _root_index(path: str, prefixes: list[str]) -> Optional[int]:
    """Index of the configured folder that holds `path` (longest match)."""
    p = os.path.normcase(path)
    best, best_len = None, -1
    for i, pre in enumerate(prefixes):
        if p == pre or p.startswith(pre + "\\") or p.startswith(pre + "/"):
            if len(pre) > best_len:
                best, best_len = i, len(pre)
    return best


def _import_art_file(
    db: Session, *, entity_kind: str, entity_id, role: str, image_path: Optional[str],
    stats: FolderScanStats,
) -> bool:
    if not image_path:
        return False
    try:
        st = os.stat(image_path)
    except OSError:
        return False
    ref = f"{image_path}|{int(st.st_mtime)}|{st.st_size}"
    existing = db.get(ArtOverride, (entity_kind, entity_id, role))
    if existing is not None and (existing.source_kind not in _SCANNER_SOURCES or existing.source_ref == ref):
        return existing.source_ref == ref
    try:
        with open(image_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    return _save_art_bytes(db, entity_kind, entity_id, role, data, ref, stats)


def _save_art_bytes(db, entity_kind, entity_id, role, data: bytes, ref: str, stats: FolderScanStats) -> bool:
    from app.services.art import ArtValidationError, SYSTEM_USER_ID, save_upload_bytes
    try:
        save_upload_bytes(
            db, entity_kind=entity_kind, entity_id=entity_id, role=role, data=data,
            set_by_user_id=SYSTEM_USER_ID, source_kind=SOURCE_LOCAL, source_ref=ref[:2000],
        )
    except ArtValidationError as exc:
        log.warning("local art skipped for %s/%s %s: %s", entity_kind, entity_id, role, exc)
        return False
    stats.art_imported += 1
    return True


def _has_art(db: Session, entity_kind: str, entity_id, role: str) -> bool:
    return db.get(ArtOverride, (entity_kind, entity_id, role)) is not None


def _fetch_tmdb_art(db: Session, entity_kind: str, entity_id, role: str, tmdb_path: Optional[str], stats: FolderScanStats) -> None:
    """Fetch a TMDB poster/backdrop when the entity has no art at all."""
    if not tmdb_path or _has_art(db, entity_kind, entity_id, role):
        return
    from app.services.art import ArtValidationError, SYSTEM_USER_ID, fetch_and_save_url
    size = "w780" if role == ROLE_POSTER else "w1280"
    try:
        fetch_and_save_url(
            db, entity_kind=entity_kind, entity_id=entity_id, role=role,
            url=f"https://image.tmdb.org/t/p/{size}{tmdb_path}",
            set_by_user_id=SYSTEM_USER_ID, source_kind=SOURCE_TMDB,
        )
        stats.art_imported += 1
    except ArtValidationError as exc:
        log.warning("tmdb art skipped for %s/%s %s: %s", entity_kind, entity_id, role, exc)


def _tmdb_search(kind: str, title: str, year: Optional[int]) -> Optional[dict]:
    if not tmdb_key.get() or not title:
        return None
    from app.services.metadata._base import ProviderError
    from app.services.metadata.tmdb import TMDBClient
    try:
        with TMDBClient() as cli:
            return cli.search(kind, title, year)
    except ProviderError as exc:
        log.warning("tmdb search failed for %s %r: %s", kind, title, exc)
        return None


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------
@dataclass
class FoundMovie:
    path: str
    title: str
    year: Optional[int]
    tmdb_id: Optional[int]
    folder: Optional[str]   # the movie's own folder, when it has one


def discover_movies(root: str) -> Iterator[FoundMovie]:
    """Yield one entry per movie file under `root`. A folder with several
    video files (multi-part rips) yields the largest one."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _is_skip_dir(d))
        videos = [f for f in filenames if _ext(f) in VIDEO_EXTS and not _is_sample(f)]
        if not videos:
            continue
        in_own_folder = os.path.normcase(os.path.abspath(dirpath)) != os.path.normcase(os.path.abspath(root))
        if in_own_folder and len(videos) > 1 and not dirnames:
            # One movie per folder: keep the biggest file, ignore the rest.
            videos = [max(videos, key=lambda f: _size(os.path.join(dirpath, f)))]
        for fname in sorted(videos):
            source = os.path.basename(dirpath) if in_own_folder else os.path.splitext(fname)[0]
            title, year = parse_title_year(source)
            if not year and in_own_folder:
                t2, y2 = parse_title_year(os.path.splitext(fname)[0])
                if y2:
                    title, year = t2, y2
            yield FoundMovie(
                path=os.path.join(dirpath, fname),
                title=title or os.path.splitext(fname)[0],
                year=year,
                tmdb_id=parse_tmdb_tag(source) or parse_tmdb_tag(fname),
                folder=dirpath if in_own_folder else None,
            )


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


_MOVIE_COPY_FIELDS = (
    "year", "overview", "runtime_min", "poster_path", "backdrop_path", "genres",
    "tagline", "movie_cast", "directors", "tmdb_rating", "tmdb_vote_count",
)


def _movie_roots(db: Session, movie: Movie, prefixes: list[str]) -> set[int]:
    paths = db.scalars(select(MediaFile.path).where(
        MediaFile.kind == MediaKind.movie, MediaFile.ref_id == movie.id,
    )).all()
    return {i for i in (_root_index(p, prefixes) for p in paths) if i is not None}


def _match_movie(db: Session, found: FoundMovie, ri: int, prefixes: list[str]) -> tuple[Optional[Movie], Optional[Movie]]:
    """Find the movie a new file belongs to. Returns (movie, twin_of): a
    match whose files all live in another folder is not reused; the caller
    makes a separate entry and copies details from `twin_of`."""
    cands: list[Movie] = []
    if found.tmdb_id:
        m = db.scalar(select(Movie).where(Movie.tmdb_id == found.tmdb_id))
        if m is not None:
            cands.append(m)
    q = select(Movie).where(func.lower(Movie.title) == found.title.lower(), Movie.radarr_id.is_(None))
    q = q.where(Movie.year == found.year) if found.year else q
    for m in db.scalars(q.order_by(Movie.created_at)).all():
        if m not in cands:
            cands.append(m)
    if not cands:
        return None, None
    owners = {m.id: _movie_roots(db, m, prefixes) for m in cands}
    for m in cands:
        if ri in owners[m.id]:
            return m, None
    for m in cands:
        if not owners[m.id]:
            return m, None
    return None, cands[0]


def _tmdb_twin(db: Session, movie: Movie) -> Optional[Movie]:
    """The entry with a TMDB id that this one duplicates (same title/year)."""
    q = select(Movie).where(
        func.lower(Movie.title) == (movie.title or "").lower(),
        Movie.tmdb_id.is_not(None), Movie.id != movie.id,
    )
    q = q.where(Movie.year == movie.year) if movie.year else q.where(Movie.year.is_(None))
    return db.scalars(q.order_by(Movie.created_at)).first()


def _copy_movie_details(src: Movie, dst: Movie, *, fill_only: bool) -> None:
    for field in _MOVIE_COPY_FIELDS:
        value = getattr(src, field)
        if value in (None, [], "") or (fill_only and getattr(dst, field) not in (None, [], "")):
            continue
        setattr(dst, field, list(value) if isinstance(value, list) else value)


def _copy_movie_art(db: Session, src: Movie, dst: Movie, stats: FolderScanStats) -> None:
    """Give a duplicate entry the first entry's poster and backdrop when it
    has none of its own. A sidecar in its own folder still wins later."""
    from app.services.art import _absolute_path
    for role in (ROLE_POSTER, ROLE_BACKDROP):
        if _has_art(db, ENTITY_MOVIE, dst.id, role):
            continue
        row = db.get(ArtOverride, (ENTITY_MOVIE, src.id, role))
        if row is None or not row.local_path:
            continue
        try:
            data = _absolute_path(row.local_path).read_bytes()
        except OSError:
            continue
        _save_art_bytes(db, ENTITY_MOVIE, dst.id, role, data, f"copy:{src.id}", stats)


def scan_movies(
    db: Session, stats: Optional[FolderScanStats] = None, on_progress: Optional[ProgressFn] = None,
) -> FolderScanStats:
    stats = stats if stats is not None else FolderScanStats()
    batch = _Batcher(db, "movies", stats, on_progress)
    roots = library_folders.folders(db, "movies")
    prefixes = _root_prefixes(roots)
    for ri, root in _reachable(roots, "movies"):
        _scan_movies_root(db, root, ri, prefixes, stats, batch)
    db.flush()
    stats.log_summary("movies")
    batch.commit()
    return stats


def _scan_movies_root(
    db: Session, root: str, ri: int, prefixes: list[str], stats: FolderScanStats, batch: _Batcher,
) -> None:
    seen: set[str] = set()
    for found in discover_movies(root):
        path = _store_path(found.path)
        seen.add(path)
        movie = None
        twin_of = None
        ref = _existing_ref(db, path, MediaKind.movie)
        if ref is not None:
            movie = db.get(Movie, ref)
        if movie is None:
            movie, twin_of = _match_movie(db, found, ri, prefixes)
        new = movie is None
        if new:
            movie = Movie(title=found.title, year=found.year, added_at=_mtime(found.path) or datetime.now(timezone.utc))
            db.add(movie)
        db.flush()
        if found.tmdb_id and movie.tmdb_id is None and db.scalar(
            select(Movie.id).where(Movie.tmdb_id == found.tmdb_id, Movie.id != movie.id)
        ) is None:
            movie.tmdb_id = found.tmdb_id
            db.flush()
        stats.movies += int(new)

        # A duplicate of a movie in another folder: copy its details instead
        # of matching TMDB again (the id belongs to the other entry).
        twin = twin_of if twin_of is not None else (_tmdb_twin(db, movie) if movie.tmdb_id is None else None)
        if twin is not None:
            _copy_movie_details(twin, movie, fill_only=twin_of is None)
            db.flush()

        # Title/year match on TMDB only for rows that have no TMDB id yet.
        # Results are disk-cached, so rescans do not re-hit the API.
        match = _tmdb_search("movie", found.title, found.year) if movie.tmdb_id is None and twin is None else None
        if match:
            clash = db.scalar(select(Movie).where(Movie.tmdb_id == match.get("id"), Movie.id != movie.id))
            if clash is None:
                movie.tmdb_id = match.get("id")
                new = True  # schedule enrichment below
            movie.overview = movie.overview or match.get("overview") or None
            released = _parse_date(match.get("release_date"))
            movie.year = movie.year or (released.year if released else None)
        if movie.tmdb_id and new:
            batch.enrich_movie(movie.id)

        _upsert_file(db, kind=MediaKind.movie, ref_id=movie.id, path=path, stats=stats)

        folder = found.folder
        stem = os.path.splitext(os.path.basename(found.path))[0]
        if folder:
            _import_art_file(db, entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_POSTER,
                             image_path=_find_sidecar(folder, ("poster", "folder", "cover", f"{stem}-poster".lower())), stats=stats)
            _import_art_file(db, entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_BACKDROP,
                             image_path=_find_sidecar(folder, ("fanart", "backdrop", "background", f"{stem}-fanart".lower())), stats=stats)
        if twin is not None:
            _copy_movie_art(db, twin, movie, stats)
        if match:
            _fetch_tmdb_art(db, ENTITY_MOVIE, movie.id, ROLE_POSTER, match.get("poster_path"), stats)
            _fetch_tmdb_art(db, ENTITY_MOVIE, movie.id, ROLE_BACKDROP, match.get("backdrop_path"), stats)
        batch.item_done()
    _mark_missing_under(db, MediaKind.movie, root, seen, stats)


# ---------------------------------------------------------------------------
# TV
# ---------------------------------------------------------------------------
@dataclass
class FoundEpisode:
    path: str
    season: int
    episode: int
    title: Optional[str]


def discover_show(show_dir: str) -> Iterator[FoundEpisode]:
    for dirpath, dirnames, filenames in os.walk(show_dir):
        dirnames[:] = sorted(d for d in dirnames if not _is_skip_dir(d) or parse_season_dir(d) is not None)
        folder_season = parse_season_dir(os.path.basename(dirpath))
        for fname in sorted(filenames):
            if _ext(fname) not in VIDEO_EXTS or _is_sample(fname):
                continue
            parsed = parse_episode(fname)
            if parsed is None:
                continue
            season, episode, title = parsed
            if folder_season == 0:
                season = 0
            yield FoundEpisode(os.path.join(dirpath, fname), season, episode, title)


def scan_tv(
    db: Session, stats: Optional[FolderScanStats] = None, on_progress: Optional[ProgressFn] = None,
) -> FolderScanStats:
    """Shows merge across folders: a show split over two drives is one
    series, and an episode found in both gets two files."""
    stats = stats if stats is not None else FolderScanStats()
    batch = _Batcher(db, "tv", stats, on_progress)
    art_done: set = set()
    for _ri, root in _reachable(library_folders.folders(db, "tv"), "tv"):
        _scan_tv_root(db, root, art_done, stats, batch)
    db.flush()
    stats.log_summary("tv")
    batch.commit()
    return stats


def _scan_tv_root(db: Session, root: str, art_done: set, stats: FolderScanStats, batch: _Batcher) -> None:
    seen: set[str] = set()
    for show_name in sorted(os.listdir(root)):
        show_dir = os.path.join(root, show_name)
        if not os.path.isdir(show_dir) or _is_skip_dir(show_name):
            continue
        episodes = list(discover_show(show_dir))
        if not episodes:
            continue
        title, year = _show_title_year(show_name)
        tmdb_tag = parse_tmdb_tag(show_name)
        scene_named = bool(_EPISODE_RE.search(show_name) or _EPISODE_X_RE.search(show_name))

        # Resolve the series this folder belongs to. A scene-named folder (the
        # episode code is in the folder name, so it holds one episode) resolves
        # by title, so every such folder collapses onto one show and a rescan
        # pulls the episode off the old per-episode series. A normal show folder
        # resolves through an episode we already indexed first, so an enriched
        # or renamed series keeps its rows instead of spawning a duplicate.
        series = None
        if tmdb_tag:
            series = db.scalar(select(Series).where(Series.tmdb_id == tmdb_tag))
        if series is None and not scene_named:
            for fe in episodes:
                ref = _existing_ref(db, _store_path(fe.path), MediaKind.episode)
                ep = db.get(Episode, ref) if ref is not None else None
                if ep is not None:
                    series = db.get(Series, ep.series_id)
                    break
        if series is None:
            series = db.scalars(select(Series).where(
                func.lower(Series.title) == title.lower(), Series.sonarr_id.is_(None),
            )).first()
        new = series is None
        if new:
            series = Series(title=title, added_at=_mtime(show_dir) or datetime.now(timezone.utc))
            db.add(series)
        if tmdb_tag and series.tmdb_id is None:
            series.tmdb_id = tmdb_tag
        db.flush()
        stats.series += int(new)

        match = None
        if series.tmdb_id is None or not series.overview:
            match = _tmdb_search("tv", title, year)
            if match:
                if series.tmdb_id is None:
                    clash = db.scalar(select(Series).where(Series.tmdb_id == match.get("id"), Series.id != series.id))
                    if clash is None:
                        series.tmdb_id = match.get("id")
                series.overview = series.overview or match.get("overview") or None
                series.first_aired = series.first_aired or _parse_date(match.get("first_air_date"))

        seasons: dict[int, Season] = {s.season_number: s for s in series.seasons}
        for fe in episodes:
            season = seasons.get(fe.season)
            if season is None:
                season = Season(series_id=series.id, season_number=fe.season)
                db.add(season)
                db.flush()
                seasons[fe.season] = season
            path = _store_path(fe.path)
            ep = db.scalar(select(Episode).where(
                Episode.series_id == series.id,
                Episode.season_number == fe.season,
                Episode.episode_number == fe.episode,
            ))
            if ep is None:
                # A rescan after the scene-folder grouping fix: this episode may
                # already exist under the old per-episode series. Move the row
                # onto the grouped show so watch history survives, instead of
                # making a duplicate and orphaning the old one.
                ref = _existing_ref(db, path, MediaKind.episode)
                moved = db.get(Episode, ref) if ref is not None else None
                if moved is not None and moved.series_id != series.id:
                    moved.series_id = series.id
                    moved.season_number = fe.season
                    moved.episode_number = fe.episode
                    ep = moved
                else:
                    ep = Episode(series_id=series.id, season_number=fe.season,
                                 episode_number=fe.episode, title=fe.title)
                    db.add(ep)
                    stats.episodes += 1
                db.flush()
            elif fe.title and not ep.title:
                ep.title = fe.title
            seen.add(path)
            _upsert_file(db, kind=MediaKind.episode, ref_id=ep.id, path=path, stats=stats)
            batch.item_done()

        # One art pick per series per pass: with the show in two folders the
        # first folder's sidecar wins, so the two don't swap every scan.
        for role, stems in ((ROLE_POSTER, ("poster", "folder", "cover")), (ROLE_BACKDROP, ("fanart", "backdrop", "background"))):
            side = _find_sidecar(show_dir, stems)
            if side and (series.id, role) not in art_done:
                art_done.add((series.id, role))
                _import_art_file(db, entity_kind=ENTITY_SERIES, entity_id=series.id, role=role, image_path=side, stats=stats)
        if match:
            _fetch_tmdb_art(db, ENTITY_SERIES, series.id, ROLE_POSTER, match.get("poster_path"), stats)
            _fetch_tmdb_art(db, ENTITY_SERIES, series.id, ROLE_BACKDROP, match.get("backdrop_path"), stats)
    _mark_missing_under(db, MediaKind.episode, root, seen, stats)


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------
@dataclass
class FoundTrack:
    path: str
    artist: str
    album: str
    title: str
    track: Optional[int]
    disc: int
    year: Optional[int]
    genre: Optional[str]
    artist_mbid: Optional[str]
    album_mbid: Optional[str]
    track_mbid: Optional[str]
    album_dir: str


def read_tags(path: str) -> dict:
    """Best-effort tag read. Returns {} when mutagen is missing or the file
    has no readable tags."""
    try:
        import mutagen  # type: ignore
    except ImportError:
        return {}
    try:
        f = mutagen.File(path, easy=True)
    except Exception:
        return {}
    if f is None or not getattr(f, "tags", None):
        return {}
    try:
        return {str(k).lower(): v for k, v in f.tags.items()}
    except Exception:
        return {}


def embedded_cover(path: str) -> Optional[bytes]:
    try:
        import mutagen  # type: ignore
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None:
        return None
    pics = getattr(f, "pictures", None)
    if pics:
        return pics[0].data
    tags = getattr(f, "tags", None)
    if tags is None:
        return None
    try:
        for key in tags.keys():
            if str(key).startswith("APIC"):
                return tags[key].data
        covr = tags.get("covr") if hasattr(tags, "get") else None
        if covr:
            return bytes(covr[0])
    except Exception:
        return None
    return None


def discover_music(root: str) -> Iterator[FoundTrack]:
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in ("@eadir", "#recycle", "$recycle.bin"))
        audio = sorted(f for f in filenames if _ext(f) in AUDIO_EXTS)
        if not audio:
            continue
        rel = os.path.relpath(os.path.abspath(dirpath), root_abs)
        parts = [] if rel == "." else rel.replace("\\", "/").split("/")
        folder_disc = None
        album_dir = dirpath
        if parts and _DISC_DIR_RE.match(parts[-1]):
            folder_disc = int(_DISC_DIR_RE.match(parts[-1]).group(1))
            parts = parts[:-1]
            album_dir = os.path.dirname(dirpath)
        folder_artist = parts[0] if len(parts) >= 1 else "Unknown Artist"
        folder_album = parts[1] if len(parts) >= 2 else (parts[0] if parts else "Unknown Album")
        for fname in audio:
            full = os.path.join(dirpath, fname)
            tags = read_tags(full)
            f_disc, f_track, f_title = parse_track_filename(fname)
            album_title, album_year = parse_title_year(folder_album)
            year_tag = _first(tags, "date", "originaldate", "year")
            yield FoundTrack(
                path=full,
                artist=_first(tags, "albumartist", "album artist", "album_artist", "artist") or folder_artist,
                album=_first(tags, "album") or album_title or folder_album,
                title=_first(tags, "title") or f_title,
                track=_num(tags.get("tracknumber")) or f_track,
                disc=_num(tags.get("discnumber")) or folder_disc or f_disc or 1,
                year=_num(year_tag) if year_tag else album_year,
                genre=_first(tags, "genre"),
                artist_mbid=normalize_mbid(_first(tags, "musicbrainz_albumartistid", "musicbrainz_artistid")),
                album_mbid=normalize_mbid(_first(tags, "musicbrainz_releasegroupid")),
                track_mbid=normalize_mbid(_first(tags, "musicbrainz_trackid")),
                album_dir=album_dir,
            )


def scan_music(
    db: Session, stats: Optional[FolderScanStats] = None, on_progress: Optional[ProgressFn] = None,
) -> FolderScanStats:
    """Artists and albums merge across folders."""
    stats = stats if stats is not None else FolderScanStats()
    batch = _Batcher(db, "music", stats, on_progress)
    cache = _MusicCache()
    for _ri, root in _reachable(library_folders.folders(db, "music"), "music"):
        _scan_music_root(db, root, cache, stats, batch)
    db.flush()
    stats.log_summary("music")
    batch.commit()
    return stats


@dataclass
class _MusicCache:
    artists: dict = None  # type: ignore[assignment]
    albums: dict = None  # type: ignore[assignment]
    album_art_done: set = None  # type: ignore[assignment]
    artist_art_done: set = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.artists, self.albums = {}, {}
        self.album_art_done, self.artist_art_done = set(), set()


def _scan_music_root(db: Session, root: str, cache: _MusicCache, stats: FolderScanStats, batch: _Batcher) -> None:
    seen: set[str] = set()
    artists = cache.artists
    albums = cache.albums
    album_art_done = cache.album_art_done
    artist_art_done = cache.artist_art_done

    for ft in discover_music(root):
        # Each file processes inside a SAVEPOINT. One bad file (for example a tag
        # that makes a row too long for its column) rolls back just that file's
        # work, is recorded with its path and a short reason, counted, and the
        # scan keeps going. The library ends "done" with an error count, never
        # "failed". The caches are shared across files, so any entry a failed
        # file added is pruned on rollback and a later good file re-creates it.
        artist_keys_before = set(artists)
        album_keys_before = set(albums)
        sp = db.begin_nested()
        try:
            _import_one_track(db, root, ft, cache, stats, batch, seen)
            sp.commit()
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            for k in set(artists) - artist_keys_before:
                del artists[k]
            for k in set(albums) - album_keys_before:
                del albums[k]
            _record_file_error(ft.path, exc, stats)
        batch.item_done()
    _mark_missing_under(db, MediaKind.track, root, seen, stats)


def _import_one_track(
    db: Session, root: str, ft: "FoundTrack", cache: _MusicCache,
    stats: FolderScanStats, batch: _Batcher, seen: set[str],
) -> None:
    """Import one music file: its artist, album, track, media file, and art.
    Runs inside the caller's savepoint so a failure undoes only this file."""
    artists = cache.artists
    albums = cache.albums
    album_art_done = cache.album_art_done
    artist_art_done = cache.artist_art_done

    akey = ft.artist.lower()
    artist = artists.get(akey)
    if artist is None:
        if ft.artist_mbid:
            artist = db.scalar(select(Artist).where(Artist.mbid == ft.artist_mbid))
        if artist is None:
            artist = db.scalars(select(Artist).where(func.lower(Artist.name) == akey)).first()
        if artist is None:
            artist = Artist(name=ft.artist)
            if ft.artist_mbid:
                artist.mbid = ft.artist_mbid
            db.add(artist)
            db.flush()
            stats.artists += 1
            if artist.mbid:
                batch.enrich_artist(artist.id)
        artists[akey] = artist

    bkey = (artist.id, ft.album.lower())
    album = albums.get(bkey)
    if album is None:
        if ft.album_mbid:
            album = db.scalar(select(Album).where(Album.mbid == ft.album_mbid))
        if album is None:
            album = db.scalars(select(Album).where(Album.artist_id == artist.id, func.lower(Album.title) == ft.album.lower())).first()
        if album is None:
            album = Album(artist_id=artist.id, title=ft.album)
            if ft.album_mbid:
                album.mbid = ft.album_mbid
            if ft.year:
                album.release_date = date(ft.year, 1, 1)
            if ft.genre:
                album.genres = [ft.genre]
            db.add(album)
            db.flush()
            stats.albums += 1
            if album.mbid:
                batch.enrich_album(album.id)
        albums[bkey] = album

    path = _store_path(ft.path)
    seen.add(path)
    track = None
    ref = _existing_ref(db, path, MediaKind.track)
    if ref is not None:
        track = db.get(Track, ref)
    if track is None and ft.track is not None:
        track = db.scalars(select(Track).where(
            Track.album_id == album.id, Track.disc_number == ft.disc, Track.track_number == ft.track,
        )).first()
    if track is None:
        track = Track(album_id=album.id, title=ft.title, track_number=ft.track, disc_number=ft.disc)
        if ft.track_mbid and db.scalar(select(Track).where(Track.mbid == ft.track_mbid)) is None:
            track.mbid = ft.track_mbid
        db.add(track)
        db.flush()
        stats.tracks += 1
    else:
        track.album_id = album.id
        track.title = ft.title or track.title
        track.track_number = ft.track
        track.disc_number = ft.disc
    mf = _upsert_file(db, kind=MediaKind.track, ref_id=track.id, path=path, stats=stats)
    if mf.duration_sec and not track.duration_sec:
        track.duration_sec = mf.duration_sec

    if album.id not in album_art_done:
        album_art_done.add(album.id)
        side = _find_sidecar(ft.album_dir, ("cover", "folder", "front", "album"))
        if side:
            _import_art_file(db, entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER, image_path=side, stats=stats)
        elif not _has_art(db, ENTITY_ALBUM, album.id, ROLE_COVER):
            data = embedded_cover(ft.path)
            if data:
                _save_art_bytes(db, ENTITY_ALBUM, album.id, ROLE_COVER, data, f"embedded:{path}", stats)
    if artist.id not in artist_art_done:
        artist_art_done.add(artist.id)
        artist_dir = os.path.dirname(ft.album_dir)
        if os.path.normcase(os.path.abspath(artist_dir)) != os.path.normcase(os.path.abspath(root)):
            _import_art_file(db, entity_kind=ENTITY_ARTIST, entity_id=artist.id, role=ROLE_THUMB,
                             image_path=_find_sidecar(artist_dir, ("artist", "folder", "poster", "thumb")), stats=stats)
