r"""Folder scanner for movies, TV, and music.

This is the no-*arr path. When a library has a LIBRARY_ROOT_* folder set and
the matching *arr API key is blank, F7FIVE0 builds that library straight from
the files on disk. When the *arr key is set, the *arr sync owns the library
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
watch history survives a drive that is briefly offline.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Iterator, Optional

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
from app.services import ffprobe
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
def movies_enabled() -> bool:
    return bool(settings.library_root_movies) and not settings.radarr_api_key


def tv_enabled() -> bool:
    return bool(settings.library_root_tv) and not settings.sonarr_api_key


def music_enabled() -> bool:
    return bool(settings.library_root_music) and not settings.lidarr_api_key


def any_enabled() -> bool:
    return movies_enabled() or tv_enabled() or music_enabled()


def scan_all(db: Session) -> FolderScanStats:
    """Scan every library this scanner owns. Each runs in its own savepoint
    so one bad library does not roll back the others."""
    total = FolderScanStats()
    for label, enabled, fn in (
        ("movies", movies_enabled, scan_movies),
        ("tv", tv_enabled, scan_tv),
        ("music", music_enabled, scan_music),
    ):
        if not enabled():
            continue
        try:
            with db.begin_nested():
                s = fn(db)
            for k in total.__dataclass_fields__:
                setattr(total, k, getattr(total, k) + getattr(s, k))
        except Exception:
            log.exception("%s folder scan failed", label)
            total.errors += 1
    return total


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
    if not settings.tmdb_api_key or not title:
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


def scan_movies(db: Session) -> FolderScanStats:
    stats = FolderScanStats()
    root = settings.library_root_movies
    if not root or not os.path.isdir(root):
        log.warning("movies root not found: %r", root)
        return stats
    seen: set[str] = set()
    for found in discover_movies(root):
        path = _store_path(found.path)
        seen.add(path)
        movie = None
        ref = _existing_ref(db, path, MediaKind.movie)
        if ref is not None:
            movie = db.get(Movie, ref)
        if movie is None and found.tmdb_id:
            movie = db.scalar(select(Movie).where(Movie.tmdb_id == found.tmdb_id))
        if movie is None:
            q = select(Movie).where(func.lower(Movie.title) == found.title.lower(), Movie.radarr_id.is_(None))
            q = q.where(Movie.year == found.year) if found.year else q
            movie = db.scalars(q).first()
        new = movie is None
        if new:
            movie = Movie(title=found.title, year=found.year, added_at=_mtime(found.path) or datetime.now(timezone.utc))
            db.add(movie)
        if found.tmdb_id and movie.tmdb_id is None:
            movie.tmdb_id = found.tmdb_id
        db.flush()
        stats.movies += int(new)

        # Title/year match on TMDB only for rows that have no TMDB id yet.
        # Results are disk-cached, so rescans do not re-hit the API.
        match = _tmdb_search("movie", found.title, found.year) if movie.tmdb_id is None else None
        if match:
            clash = db.scalar(select(Movie).where(Movie.tmdb_id == match.get("id"), Movie.id != movie.id))
            if clash is None:
                movie.tmdb_id = match.get("id")
                new = True  # schedule enrichment below
            movie.overview = movie.overview or match.get("overview") or None
            released = _parse_date(match.get("release_date"))
            movie.year = movie.year or (released.year if released else None)
        if movie.tmdb_id and new:
            scheduler.schedule_enrich_movie(movie.id)

        _upsert_file(db, kind=MediaKind.movie, ref_id=movie.id, path=path, stats=stats)

        folder = found.folder
        stem = os.path.splitext(os.path.basename(found.path))[0]
        if folder:
            _import_art_file(db, entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_POSTER,
                             image_path=_find_sidecar(folder, ("poster", "folder", "cover", f"{stem}-poster".lower())), stats=stats)
            _import_art_file(db, entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_BACKDROP,
                             image_path=_find_sidecar(folder, ("fanart", "backdrop", "background", f"{stem}-fanart".lower())), stats=stats)
        if match:
            _fetch_tmdb_art(db, ENTITY_MOVIE, movie.id, ROLE_POSTER, match.get("poster_path"), stats)
            _fetch_tmdb_art(db, ENTITY_MOVIE, movie.id, ROLE_BACKDROP, match.get("backdrop_path"), stats)
    _mark_missing_under(db, MediaKind.movie, root, seen, stats)
    db.flush()
    stats.log_summary("movies")
    return stats


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


def scan_tv(db: Session) -> FolderScanStats:
    stats = FolderScanStats()
    root = settings.library_root_tv
    if not root or not os.path.isdir(root):
        log.warning("tv root not found: %r", root)
        return stats
    seen: set[str] = set()
    for show_name in sorted(os.listdir(root)):
        show_dir = os.path.join(root, show_name)
        if not os.path.isdir(show_dir) or _is_skip_dir(show_name):
            continue
        episodes = list(discover_show(show_dir))
        if not episodes:
            continue
        title, year = parse_title_year(show_name)
        title = title or show_name
        tmdb_tag = parse_tmdb_tag(show_name)

        series = None
        for fe in episodes:
            ref = _existing_ref(db, _store_path(fe.path), MediaKind.episode)
            ep = db.get(Episode, ref) if ref is not None else None
            if ep is not None:
                series = db.get(Series, ep.series_id)
                break
        if series is None and tmdb_tag:
            series = db.scalar(select(Series).where(Series.tmdb_id == tmdb_tag))
        if series is None:
            series = db.scalars(select(Series).where(func.lower(Series.title) == title.lower(), Series.sonarr_id.is_(None))).first()
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
            ep = db.scalar(select(Episode).where(
                Episode.series_id == series.id,
                Episode.season_number == fe.season,
                Episode.episode_number == fe.episode,
            ))
            if ep is None:
                ep = Episode(series_id=series.id, season_number=fe.season, episode_number=fe.episode, title=fe.title)
                db.add(ep)
                db.flush()
                stats.episodes += 1
            elif fe.title and not ep.title:
                ep.title = fe.title
            path = _store_path(fe.path)
            seen.add(path)
            _upsert_file(db, kind=MediaKind.episode, ref_id=ep.id, path=path, stats=stats)

        _import_art_file(db, entity_kind=ENTITY_SERIES, entity_id=series.id, role=ROLE_POSTER,
                         image_path=_find_sidecar(show_dir, ("poster", "folder", "cover")), stats=stats)
        _import_art_file(db, entity_kind=ENTITY_SERIES, entity_id=series.id, role=ROLE_BACKDROP,
                         image_path=_find_sidecar(show_dir, ("fanart", "backdrop", "background")), stats=stats)
        if match:
            _fetch_tmdb_art(db, ENTITY_SERIES, series.id, ROLE_POSTER, match.get("poster_path"), stats)
            _fetch_tmdb_art(db, ENTITY_SERIES, series.id, ROLE_BACKDROP, match.get("backdrop_path"), stats)
    _mark_missing_under(db, MediaKind.episode, root, seen, stats)
    db.flush()
    stats.log_summary("tv")
    return stats


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
                artist_mbid=_first(tags, "musicbrainz_albumartistid", "musicbrainz_artistid"),
                album_mbid=_first(tags, "musicbrainz_releasegroupid"),
                track_mbid=_first(tags, "musicbrainz_trackid"),
                album_dir=album_dir,
            )


def scan_music(db: Session) -> FolderScanStats:
    stats = FolderScanStats()
    root = settings.library_root_music
    if not root or not os.path.isdir(root):
        log.warning("music root not found: %r", root)
        return stats
    seen: set[str] = set()
    artists: dict[str, Artist] = {}
    albums: dict[tuple, Album] = {}
    album_art_done: set = set()
    artist_art_done: set = set()

    for ft in discover_music(root):
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
                    scheduler.schedule_enrich_artist(artist.id)
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
                    scheduler.schedule_enrich_album(album.id)
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
    _mark_missing_under(db, MediaKind.track, root, seen, stats)
    db.flush()
    stats.log_summary("music")
    return stats
