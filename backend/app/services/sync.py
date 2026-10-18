"""*arr sync service.

Responsibilities:
    - Pull canonical metadata from Radarr / Sonarr / Lidarr.
    - Upsert into movies / series / seasons / episodes / artists / albums /
      tracks / music_videos.
    - Maintain `media_files` rows keyed by (path) unique, with (kind, ref_id)
      pointing at the canonical row.
    - Run ffprobe for new paths, flipping `scan_state` to ready/missing/error.

Two entry points:
    full_sync(db)                — run everything in order. Used by the scheduler.
    refresh_movie/series/artist  — single-record refreshes. Used by webhooks.

All DB work goes through the caller's Session. `full_sync` saves as it goes
(every BATCH_SIZE items, and at least every PROGRESS_EVERY_SEC seconds), the way
the folder scan does, so rows show up in the library while an app syncs and a
failure partway loses only the open batch. The other entry points leave the
commit to the caller. Enrichment jobs are not scheduled while the sync runs: the
ids are collected on `SyncStats` and the caller hands them to
`schedule_pending_enrichment` after its commit, so a job never runs before the
row it enriches is visible.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import delete, select
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
from app.services import arr_library_map, arr_settings, ffprobe
from app.services.credits import resolve_artist
from app.services.arr import LidarrClient, RadarrClient, SonarrClient
from app.services.arr._base import ArrClientError
from app.services.art import download_art_on_sync
from app.services import media_paths
from app.services.path_map import translate as translate_path


log = logging.getLogger("f7five0.sync")

# RescanSeries is usually a few seconds, but a big folder on a cold NAS can
# take longer. We poll at 1s and give up after this many seconds; the refresh
# still runs so Sonarr catches up on the next tick either way.
_RESCAN_POLL_INTERVAL_SEC = 1.0
_RESCAN_POLL_TIMEOUT_SEC = 60.0
# ManualImport does the actual hashing / moving / file-slot work. Sonarr runs
# it on a single-threaded command queue, and several large files can stack up,
# so we give it more headroom than RescanSeries.
_MANUAL_IMPORT_POLL_TIMEOUT_SEC = 180.0

# `full_sync` commits after this many items of one app (a movie, a series, an
# artist), and writes Admin's progress then. Same size as the folder scan's
# batch. Never more than 50 per commit.
BATCH_SIZE = 25
# A slow item (a big series on a cold NAS) must not leave Admin silent: save and
# report at least this often while an app runs.
PROGRESS_EVERY_SEC = 5.0


@dataclass
class SyncStats:
    movies_upserted: int = 0
    series_upserted: int = 0
    episodes_upserted: int = 0
    artists_upserted: int = 0
    albums_upserted: int = 0
    tracks_upserted: int = 0
    files_upserted: int = 0
    files_probed: int = 0
    # Files that ended this run in the `ready` state (probed now or already ready).
    files_ready: int = 0
    files_missing: int = 0
    files_pruned: int = 0
    # Paths an *arr app reported outside the library folders: never probed,
    # never stored (services/media_paths.py).
    files_refused: int = 0
    # Missing files by the drive letter their stored path starts with ("N:"),
    # so Admin can say the service cannot see a mapped drive (services/path_map).
    missing_drives: dict = field(default_factory=dict)
    errors: int = 0
    # Rows to enrich once the caller has committed (see schedule_pending_enrichment).
    pending_movies: list = field(default_factory=list)
    pending_artists: list = field(default_factory=list)
    pending_albums: list = field(default_factory=list)
    # The running app's progress reporter, set by full_sync (None outside it).
    progress: Any = field(default=None, repr=False)

    def log_summary(self) -> None:
        log.info(
            "sync complete: movies=%d series=%d eps=%d artists=%d albums=%d tracks=%d "
            "files=%d probed=%d missing=%d pruned=%d refused=%d errors=%d",
            self.movies_upserted, self.series_upserted, self.episodes_upserted,
            self.artists_upserted, self.albums_upserted, self.tracks_upserted,
            self.files_upserted, self.files_probed, self.files_missing,
            self.files_pruned, self.files_refused, self.errors,
        )


def schedule_pending_enrichment(stats: Optional[SyncStats]) -> None:
    """Queue enrichment for the rows this sync collected. Call it after the
    session that ran the sync has committed. Each id is handed over once."""
    if stats is None:
        return
    movies, artists, albums = stats.pending_movies, stats.pending_artists, stats.pending_albums
    stats.pending_movies, stats.pending_artists, stats.pending_albums = [], [], []
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


# ---------------------------------------------------------------------------
# Full sync
# ---------------------------------------------------------------------------
def _synced_count(app: str, stats: SyncStats) -> int:
    """The items an app has brought in so far: movies, series, artists."""
    return {
        "radarr": stats.movies_upserted,
        "sonarr": stats.series_upserted,
        "lidarr": stats.artists_upserted,
    }[app]


_DRIVE_RE = re.compile(r"^([A-Za-z]:)[\\/]")


def drive_of(path: str) -> Optional[str]:
    """"N:" for a path that starts with a drive letter, else None."""
    m = _DRIVE_RE.match(path or "")
    return m.group(1).upper() if m else None


def _drive_visible(drive: str) -> bool:
    """Whether this process can open the drive's root. A drive mapped only in
    someone's Windows login is not there for a service running as LocalSystem."""
    try:
        return os.path.isdir(drive + "\\")
    except OSError:
        return False


class _AppProgress:
    """Saves and reports one app's sync as it goes.

    The app's loop calls `begin(total)` once it knows how many items it has,
    then `item_done()` after each one. Every BATCH_SIZE items (or
    PROGRESS_EVERY_SEC seconds) it commits the session and then reports, so what
    Admin shows is never ahead of what the library holds. `rollback()` drops
    the open batch after a failure and says how far the saved part got."""

    def __init__(self, db: Session, stats: SyncStats, app: str, on_progress) -> None:
        self.db = db
        self.stats = stats
        self.app = app
        self.on_progress = on_progress
        self.total = 0
        self.done = 0
        self._last = time.monotonic()
        self._base = self._tally()
        self._saved = self.counts(0)
        self._marks = self._pending_marks()

    def _tally(self) -> dict:
        s = self.stats
        return {
            "synced": _synced_count(self.app, s), "errors": s.errors, "ready": s.files_ready,
            "missing": s.files_missing, "refused": s.files_refused,
            "drives": dict(s.missing_drives),
        }

    def counts(self, done: int) -> dict:
        """What has happened since this app started, with `done` items saved.
        `missing_drive` / `missing_drive_count` name the drive letter most of the
        missing files are on, when it is at least half of them."""
        now = self._tally()
        out = {k: now[k] - self._base[k] for k in now if k != "drives"}
        drives = {
            d: n - self._base["drives"].get(d, 0)
            for d, n in now["drives"].items() if n - self._base["drives"].get(d, 0) > 0
        }
        out.update(done=done, total=max(self.total, done))
        if drives:
            drive, n = max(drives.items(), key=lambda kv: kv[1])
            if n * 2 >= out["missing"]:
                out.update(missing_drive=drive, missing_drive_count=n)
        return out

    def _pending_marks(self) -> tuple:
        s = self.stats
        return (len(s.pending_movies), len(s.pending_artists), len(s.pending_albums))

    def _report(self, state: str, counts: dict, error: Optional[str] = None) -> None:
        if self.on_progress is not None:
            self.on_progress(self.app, state, counts["synced"], counts["errors"], error, counts)

    def begin(self, total: int) -> None:
        self.total = total
        self._report("running", self.counts(0))

    def item_done(self) -> None:
        self.done += 1
        if self.done % BATCH_SIZE == 0 or time.monotonic() - self._last >= PROGRESS_EVERY_SEC:
            self.save()

    def save(self) -> None:
        self.db.commit()
        self._last = time.monotonic()
        self._saved = self.counts(self.done)
        self._marks = self._pending_marks()
        self._report("running", self._saved)

    def finish(self) -> dict:
        """The app ran to the end: commit the last batch and return its counts."""
        self.db.commit()
        self.total = max(self.total, self.done)
        return self.counts(self.done)

    def rollback(self) -> dict:
        """The app failed: drop the open batch and return what was saved."""
        self.db.rollback()
        s = self.stats
        del s.pending_movies[self._marks[0]:]
        del s.pending_artists[self._marks[1]:]
        del s.pending_albums[self._marks[2]:]
        counts = dict(self._saved)
        counts["errors"] += 1
        return counts


def _tick(stats: SyncStats) -> None:
    """One item of the running app is done (no-op outside full_sync)."""
    if stats.progress is not None:
        stats.progress.item_done()


def _begin_app(stats: SyncStats, total: int) -> None:
    if stats.progress is not None:
        stats.progress.begin(total)


def full_sync(
    db: Session,
    only: Optional[list] = None,
    on_progress: Optional[Callable[..., None]] = None,
) -> SyncStats:
    """Run a full pass across the *arr services. Returns aggregate stats.

    Each app saves as it goes: the session is committed every BATCH_SIZE items
    (see _AppProgress), so rows show up while it runs. If an app raises, its open
    batch is rolled back, the batches before it stay, and the next app still
    runs (a failure in one, e.g. Sonarr, does not stop the others).

    `only` limits the pass to the named apps (still skipping any that has no
    key). `on_progress(app, state, synced, errors, error, counts)` is told when
    each app starts ("running"), after every saved batch, and when it ends
    ("done" or "failed"), for Admin's status. `counts` has done, total, ready,
    missing, refused and errors; `done` is the items saved.
    """
    stats = SyncStats()
    for label, runner in (
        ("radarr", _run_radarr),
        ("sonarr", _run_sonarr),
        ("lidarr", _run_lidarr),
    ):
        if only is not None and label not in only:
            continue
        if not arr_settings.configured(label):
            continue
        progress = _AppProgress(db, stats, label, on_progress)
        stats.progress = progress
        if on_progress is not None:
            on_progress(label, "running", 0, 0, None, progress.counts(0))
        error = None
        try:
            runner(db, stats)
            counts = progress.finish()
        except Exception as exc:
            log.exception("%s sync failed", label)
            stats.errors += 1
            error = f"{label} sync failed: {exc}"
            counts = progress.rollback()
        finally:
            stats.progress = None
        if on_progress is not None:
            on_progress(
                label, "failed" if error else "done",
                counts["synced"], counts["errors"], error, counts,
            )
    stats.log_summary()
    return stats


def _run_radarr(db: Session, stats: SyncStats) -> None:
    with RadarrClient(*arr_settings.creds("radarr")) as rc:
        _sync_radarr(db, rc, stats)


def _run_sonarr(db: Session, stats: SyncStats) -> None:
    with SonarrClient(*arr_settings.creds("sonarr")) as sc:
        _sync_sonarr(db, sc, stats)


def _run_lidarr(db: Session, stats: SyncStats) -> None:
    with LidarrClient(*arr_settings.creds("lidarr")) as lc:
        _sync_lidarr(db, lc, stats)


# ---------------------------------------------------------------------------
# Radarr
# ---------------------------------------------------------------------------
def _resolve_requests(db: Session, kind: str, external_id) -> None:
    """Flip approved requests for this item to available once it syncs in.

    Keyed on (kind, external_id): external_id is the TMDB id for movies and
    the TVDB id for series, matched as a string. Only approved rows advance;
    pending rows still wait for an admin and denied rows stay denied.
    Stamps resolved_at. No-op when nothing matches."""
    from datetime import datetime, timezone

    from app.models.request import Request, STATUS_APPROVED, STATUS_AVAILABLE

    db.query(Request).filter(
        Request.kind == kind,
        Request.external_id == str(external_id),
        Request.status == STATUS_APPROVED,
    ).update(
        {"status": STATUS_AVAILABLE, "resolved_at": datetime.now(timezone.utc)},
        synchronize_session=False,
    )


def _sync_radarr(db: Session, rc: RadarrClient, stats: SyncStats) -> None:
    movies = rc.list_movies()
    _begin_app(stats, len(movies))
    for payload in movies:
        _upsert_movie(db, payload, stats, throttle=True)
        _tick(stats)
    db.flush()


def _upsert_movie(
    db: Session, payload: dict[str, Any], stats: SyncStats, *, throttle: bool = False,
) -> Movie:
    radarr_id = payload.get("id")
    # Radarr sends 0 / "" when a metadata id is unknown. Coerce to None so
    # many unmapped rows don't collide on the UNIQUE index AND so the
    # "fallback lookup by tmdb_id" below doesn't silently merge them.
    tmdb_id = _nullify_sentinel(payload.get("tmdbId"))
    imdb_id = _nullify_sentinel(payload.get("imdbId"))

    movie = db.scalar(select(Movie).where(Movie.radarr_id == radarr_id))
    if movie is None and tmdb_id is not None:
        movie = db.scalar(select(Movie).where(Movie.tmdb_id == tmdb_id))

    if movie is None:
        movie = Movie()
        db.add(movie)

    movie.radarr_id = radarr_id
    movie.tmdb_id = tmdb_id
    movie.imdb_id = imdb_id
    movie.title = payload.get("title") or movie.title or "Untitled"
    movie.year = payload.get("year")
    movie.overview = payload.get("overview")
    movie.runtime_min = payload.get("runtime")
    movie.genres = payload.get("genres")

    images = payload.get("images") or []

    added = payload.get("added")
    if added:
        movie.added_at = _parse_iso(added)

    db.flush()  # populate movie.id
    stats.movies_upserted += 1
    if tmdb_id is not None:
        _resolve_requests(db, "movie", tmdb_id)
    stats.pending_movies.append(movie.id)

    _throttle_after(
        download_art_on_sync(
            db,
            entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_POSTER,
            images=images, cover_type="poster", source_kind="radarr",
            arr_base_url=arr_settings.url("radarr"), arr_api_key=arr_settings.api_key("radarr"),
        ),
        throttle=throttle,
    )
    backdrop = download_art_on_sync(
        db,
        entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_BACKDROP,
        images=images, cover_type="fanart", source_kind="radarr",
        arr_base_url=arr_settings.url("radarr"),
    )
    if backdrop is None:
        backdrop = download_art_on_sync(
            db,
            entity_kind=ENTITY_MOVIE, entity_id=movie.id, role=ROLE_BACKDROP,
            images=images, cover_type="banner", source_kind="radarr",
            arr_base_url=arr_settings.url("radarr"), arr_api_key=arr_settings.api_key("radarr"),
        )
    _throttle_after(backdrop, throttle=throttle)

    mf = payload.get("movieFile") or {}
    path = mf.get("path")
    if path and payload.get("hasFile"):
        _upsert_media_file(
            db,
            kind=MediaKind.movie,
            ref_id=movie.id,
            path=path,
            arr_file=mf,
            stats=stats,
            app="radarr",
        )
    else:
        _mark_missing_for_ref(db, MediaKind.movie, movie.id, stats)

    return movie


# ---------------------------------------------------------------------------
# Sonarr
# ---------------------------------------------------------------------------
def _sync_sonarr(db: Session, sc: SonarrClient, stats: SyncStats) -> None:
    series_list = sc.list_series()
    _begin_app(stats, len(series_list))
    for s_payload in series_list:
        series = _upsert_series(db, s_payload, stats, throttle=True)
        sonarr_series_id = s_payload.get("id")
        if sonarr_series_id is None:
            _tick(stats)
            continue
        episodes = sc.list_episodes(sonarr_series_id)
        episode_files = sc.list_episode_files(sonarr_series_id)
        files_by_id = {f["id"]: f for f in episode_files}

        # Ensure every needed season row exists
        season_cache: dict[int, Season] = {
            s.season_number: s for s in series.seasons
        }
        for ep_payload in episodes:
            season_num = ep_payload.get("seasonNumber")
            if season_num is None:
                continue
            season = season_cache.get(season_num)
            if season is None:
                season = Season(
                    series_id=series.id, season_number=season_num,
                )
                db.add(season)
                season_cache[season_num] = season
                db.flush()
            _upsert_episode(db, series, ep_payload, files_by_id, stats)
        db.flush()
        _tick(stats)


def _upsert_series(
    db: Session, payload: dict[str, Any], stats: SyncStats, *, throttle: bool = False,
) -> Series:
    sonarr_id = payload.get("id")
    # Sonarr sends 0 when a metadata id is unknown. Same reasoning as movies.
    tvdb_id = _nullify_sentinel(payload.get("tvdbId"))
    tmdb_id = _nullify_sentinel(payload.get("tmdbId"))

    series = db.scalar(select(Series).where(Series.sonarr_id == sonarr_id))
    if series is None and tvdb_id is not None:
        series = db.scalar(select(Series).where(Series.tvdb_id == tvdb_id))

    if series is None:
        series = Series()
        db.add(series)

    series.sonarr_id = sonarr_id
    series.tvdb_id = tvdb_id
    series.tmdb_id = tmdb_id
    series.title = payload.get("title") or series.title or "Untitled"
    series.overview = payload.get("overview")

    images = payload.get("images") or []

    first_aired = payload.get("firstAired")
    if first_aired:
        series.first_aired = _parse_iso(first_aired).date() if "T" in first_aired else _parse_iso(first_aired + "T00:00:00Z").date()

    added = payload.get("added")
    if added:
        series.added_at = _parse_iso(added)

    db.flush()
    stats.series_upserted += 1
    if tvdb_id is not None:
        _resolve_requests(db, "series", tvdb_id)

    _throttle_after(
        download_art_on_sync(
            db,
            entity_kind=ENTITY_SERIES, entity_id=series.id, role=ROLE_POSTER,
            images=images, cover_type="poster", source_kind="sonarr",
            arr_base_url=arr_settings.url("sonarr"), arr_api_key=arr_settings.api_key("sonarr"),
        ),
        throttle=throttle,
    )
    backdrop = download_art_on_sync(
        db,
        entity_kind=ENTITY_SERIES, entity_id=series.id, role=ROLE_BACKDROP,
        images=images, cover_type="fanart", source_kind="sonarr",
        arr_base_url=arr_settings.url("sonarr"),
    )
    if backdrop is None:
        backdrop = download_art_on_sync(
            db,
            entity_kind=ENTITY_SERIES, entity_id=series.id, role=ROLE_BACKDROP,
            images=images, cover_type="banner", source_kind="sonarr",
            arr_base_url=arr_settings.url("sonarr"), arr_api_key=arr_settings.api_key("sonarr"),
        )
    _throttle_after(backdrop, throttle=throttle)
    return series


def _upsert_episode(
    db: Session,
    series: Series,
    payload: dict[str, Any],
    files_by_id: dict[int, dict[str, Any]],
    stats: SyncStats,
) -> Optional[Episode]:
    season_num = payload.get("seasonNumber")
    ep_num = payload.get("episodeNumber")
    if season_num is None or ep_num is None:
        return None

    episode = db.scalar(
        select(Episode).where(
            Episode.series_id == series.id,
            Episode.season_number == season_num,
            Episode.episode_number == ep_num,
        )
    )
    if episode is None:
        episode = Episode(
            series_id=series.id,
            season_number=season_num,
            episode_number=ep_num,
        )
        db.add(episode)

    episode.title = payload.get("title")
    episode.overview = payload.get("overview")
    episode.tvdb_id = payload.get("tvdbId")
    air = payload.get("airDateUtc") or payload.get("airDate")
    if air:
        try:
            episode.air_date = _parse_iso(air).date() if "T" in air else _parse_iso(air + "T00:00:00Z").date()
        except ValueError:
            pass

    db.flush()
    stats.episodes_upserted += 1

    ep_file_id = payload.get("episodeFileId") or 0
    if payload.get("hasFile") and ep_file_id and ep_file_id in files_by_id:
        mf = files_by_id[ep_file_id]
        path = mf.get("path")
        if path:
            _upsert_media_file(
                db,
                kind=MediaKind.episode,
                ref_id=episode.id,
                path=path,
                arr_file=mf,
                stats=stats,
                app="sonarr",
            )
    else:
        _mark_missing_for_ref(db, MediaKind.episode, episode.id, stats)

    return episode


# ---------------------------------------------------------------------------
# Lidarr
# ---------------------------------------------------------------------------
def _sync_lidarr(db: Session, lc: LidarrClient, stats: SyncStats) -> None:
    artists = lc.list_artists()
    _begin_app(stats, len(artists))
    for a_payload in artists:
        artist = _upsert_artist(db, a_payload, stats, throttle=True)
        lidarr_artist_id = a_payload.get("id")
        if lidarr_artist_id is None:
            _tick(stats)
            continue

        track_files = lc.list_track_files(lidarr_artist_id)
        files_by_id = {f["id"]: f for f in track_files}

        albums = lc.list_albums(lidarr_artist_id)
        for alb_payload in albums:
            album = _upsert_album(db, artist, alb_payload, stats, throttle=True)
            lidarr_album_id = alb_payload.get("id")
            if lidarr_album_id is None:
                continue
            tracks = lc.list_tracks(lidarr_album_id)
            for trk_payload in tracks:
                _upsert_track(db, album, trk_payload, files_by_id, stats)
        db.flush()
        _tick(stats)


def _upsert_artist(
    db: Session, payload: dict[str, Any], stats: SyncStats, *, throttle: bool = False,
) -> Artist:
    lidarr_id = payload.get("id")
    mbid = _nullify_sentinel(payload.get("foreignArtistId"))
    name = payload.get("artistName") or "Unknown Artist"

    # Route the incoming artist through any saved merge alias first. A merged-away
    # source (a collaboration credit an admin folded into the main artist)
    # resolves to its target instead of being recreated on the next sync. When an
    # alias matches, write the sync's fields onto the target row and keep the
    # target's own mbid / name.
    res_name, res_mbid, target = resolve_artist(db, name=name, mbid=mbid)
    if target is not None:
        artist = target
        stats.artists_upserted += 1
        stats.pending_artists.append(artist.id)
        return artist

    artist = db.scalar(select(Artist).where(Artist.lidarr_id == lidarr_id))
    if artist is None and mbid:
        artist = db.scalar(select(Artist).where(Artist.mbid == mbid))
    if artist is None:
        artist = Artist()
        db.add(artist)

    artist.lidarr_id = lidarr_id
    artist.mbid = mbid
    artist.name = payload.get("artistName") or artist.name or "Unknown Artist"
    artist.overview = payload.get("overview")
    artist.genres = _genres(payload)

    db.flush()
    stats.artists_upserted += 1
    stats.pending_artists.append(artist.id)

    images = payload.get("images") or []
    thumb = download_art_on_sync(
        db,
        entity_kind=ENTITY_ARTIST, entity_id=artist.id, role=ROLE_THUMB,
        images=images, cover_type="poster", source_kind="lidarr",
        arr_base_url=arr_settings.url("lidarr"),
    )
    if thumb is None:
        thumb = download_art_on_sync(
            db,
            entity_kind=ENTITY_ARTIST, entity_id=artist.id, role=ROLE_THUMB,
            images=images, cover_type="banner", source_kind="lidarr",
            arr_base_url=arr_settings.url("lidarr"), arr_api_key=arr_settings.api_key("lidarr"),
        )
    _throttle_after(thumb, throttle=throttle)
    return artist


def _upsert_album(
    db: Session, artist: Artist, payload: dict[str, Any], stats: SyncStats,
    *, throttle: bool = False,
) -> Album:
    mbid = _nullify_sentinel(payload.get("foreignAlbumId"))
    album = None
    if mbid:
        album = db.scalar(select(Album).where(Album.mbid == mbid))
    if album is None:
        album = db.scalar(
            select(Album).where(
                Album.artist_id == artist.id,
                Album.title == (payload.get("title") or ""),
            )
        )
    if album is None:
        album = Album(artist_id=artist.id, title=payload.get("title") or "Untitled")
        db.add(album)

    album.artist_id = artist.id
    album.mbid = mbid
    album.title = payload.get("title") or album.title or "Untitled"
    release = payload.get("releaseDate")
    if release:
        try:
            album.release_date = _parse_iso(release).date() if "T" in release else _parse_iso(release + "T00:00:00Z").date()
        except ValueError:
            pass
    album.genres = _genres(payload)

    # Copy Lidarr-supplied metadata fields the metadata-enrichment runner
    # may also touch on its MB pass. Doing it here means the row carries
    # something useful even before the deferred enrichment fires (and on
    # rows where MB returns no release-group).
    album_type = payload.get("albumType")
    if isinstance(album_type, str) and album_type.strip():
        album.album_type = album_type.strip()
    secondaries = payload.get("secondaryTypes") or []
    if isinstance(secondaries, list):
        album.secondary_types = [s for s in secondaries if isinstance(s, str)]
    disambiguation = payload.get("disambiguation")
    if isinstance(disambiguation, str):
        album.disambiguation = disambiguation or None
    label_value = payload.get("label")
    if isinstance(label_value, list) and label_value:
        first = label_value[0]
        if isinstance(first, str) and first.strip():
            album.label = first.strip()[:256]
    elif isinstance(label_value, str) and label_value.strip():
        album.label = label_value.strip()[:256]

    db.flush()
    stats.albums_upserted += 1
    stats.pending_albums.append(album.id)

    album_images = payload.get("images") or []
    cover = download_art_on_sync(
        db,
        entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER,
        images=album_images, cover_type="cover", source_kind="lidarr",
        arr_base_url=arr_settings.url("lidarr"),
    )
    if cover is None:
        cover = download_art_on_sync(
            db,
            entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER,
            images=album_images, cover_type="poster", source_kind="lidarr",
            arr_base_url=arr_settings.url("lidarr"), arr_api_key=arr_settings.api_key("lidarr"),
        )
    _throttle_after(cover, throttle=throttle)
    return album


def _upsert_track(
    db: Session,
    album: Album,
    payload: dict[str, Any],
    files_by_id: dict[int, dict[str, Any]],
    stats: SyncStats,
) -> Track:
    mbid = _nullify_sentinel(payload.get("foreignTrackId"))
    # Lidarr returns trackNumber as a string (e.g. "1", "A1" for vinyl sides).
    # mediumNumber comes back as int but we coerce defensively.
    track_number = _safe_int(payload.get("trackNumber"))
    disc_number = _safe_int(payload.get("mediumNumber")) or 1

    track = None
    if mbid:
        track = db.scalar(select(Track).where(Track.mbid == mbid))
    if track is None:
        track = db.scalar(
            select(Track).where(
                Track.album_id == album.id,
                Track.disc_number == disc_number,
                Track.track_number == track_number,
            )
        )
    if track is None:
        track = Track(
            album_id=album.id,
            title=payload.get("title") or "Untitled",
            track_number=track_number,
            disc_number=disc_number,
        )
        db.add(track)

    track.mbid = mbid
    track.title = payload.get("title") or track.title or "Untitled"
    track.track_number = track_number
    track.disc_number = disc_number
    track.duration_sec = _ms_to_seconds(payload.get("duration"))

    db.flush()
    stats.tracks_upserted += 1

    file_id = payload.get("trackFileId") or 0
    if payload.get("hasFile") and file_id and file_id in files_by_id:
        mf = files_by_id[file_id]
        path = mf.get("path")
        if path:
            _upsert_media_file(
                db,
                kind=MediaKind.track,
                ref_id=track.id,
                path=path,
                arr_file=mf,
                stats=stats,
                app="lidarr",
            )
    else:
        _mark_missing_for_ref(db, MediaKind.track, track.id, stats)

    return track


# ---------------------------------------------------------------------------
# Media file helpers
# ---------------------------------------------------------------------------
def _upsert_media_file(
    db: Session,
    *,
    kind: MediaKind,
    ref_id,
    path: str,
    arr_file: dict[str, Any],
    stats: SyncStats,
    app: Optional[str] = None,
) -> Optional[MediaFile]:
    # Rewrite any user-session-only drive letters (e.g. `N:\\`) to the UNC
    # path before the UNIQUE lookup. Keeps stored paths canonical and makes
    # every downstream read (ffprobe, os.path.exists, HLS) resolve under
    # whatever account the service is running as.
    path = translate_path(path, db) or path
    # The path comes from a remote service. Hold it to the library folders
    # before anything stats, probes or stores it, so a hostile or mistaken
    # *arr cannot get an outside file parsed or marked ready.
    if not media_paths.is_contained(db, path):
        stats.files_refused += 1
        log.warning(
            "refused *arr path outside the library folders (kind=%s ref_id=%s): %s",
            kind.value, ref_id, path,
        )
        return None
    existing = db.scalar(select(MediaFile).where(MediaFile.path == path))
    if existing is None:
        mf = MediaFile(kind=kind, ref_id=ref_id, path=path)
        db.add(mf)
    else:
        mf = existing
        mf.kind = kind
        mf.ref_id = ref_id

    # Stamp the library this *arr root folder maps to (per-library *arr mapping,
    # defaulting to the first library of the app's kind).
    if app is not None:
        lib_id = arr_library_map.library_for(db, app, path)
        if lib_id is not None:
            mf.library_id = lib_id

    mf.size_bytes = arr_file.get("size") or mf.size_bytes

    # Seed codec info from the *arr payload; ffprobe will overwrite with the truth.
    media_info = arr_file.get("mediaInfo") or {}
    if media_info:
        mf.video_codec = media_info.get("videoCodec") or mf.video_codec
        mf.audio_codec = media_info.get("audioCodec") or mf.audio_codec
        mf.audio_channels = _first_int(media_info.get("audioChannels")) or mf.audio_channels
        mf.width = media_info.get("width") or mf.width
        mf.height = media_info.get("height") or mf.height
        mf.duration_sec = _ms_to_seconds(media_info.get("runTime")) or mf.duration_sec

    if not mf.container:
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        mf.container = ext or None

    db.flush()
    stats.files_upserted += 1

    # Probe when we haven't yet, or when the file isn't in 'ready' state.
    if mf.scan_state != ScanState.ready or mf.probed_at is None:
        _probe_and_update(db, mf, stats)
    if mf.scan_state == ScanState.ready:
        stats.files_ready += 1

    # Drop stale siblings. Sonarr/Radarr/Lidarr each hold exactly one current
    # file per item, so any other MediaFile with the same (kind, ref_id) at a
    # different path is a leftover from a prior rename or re-import. Keeping
    # it around surfaces a stale 'missing' (or worse, 'ready' but dead) row on
    # the detail page alongside the real file. FK cascades from
    # watch_progress and watch_history handle the user-facing side cleanly.
    pruned = db.execute(
        delete(MediaFile).where(
            MediaFile.kind == kind,
            MediaFile.ref_id == ref_id,
            MediaFile.path != path,
        )
    ).rowcount or 0
    if pruned:
        stats.files_pruned += pruned
        log.info(
            "pruned %d stale media_file rows for kind=%s ref_id=%s",
            pruned, kind.value, ref_id,
        )
    return mf


def _probe_and_update(db: Session, mf: MediaFile, stats: SyncStats) -> None:
    result = ffprobe.probe(mf.path)
    if result is None:
        if not os.path.exists(mf.path):
            mf.scan_state = ScanState.missing
            stats.files_missing += 1
            drive = drive_of(mf.path)
            # Only a drive letter this process cannot open counts: a file missing
            # from a drive that is here is just missing.
            if drive and not _drive_visible(drive):
                stats.missing_drives[drive] = stats.missing_drives.get(drive, 0) + 1
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


def _mark_missing_for_ref(
    db: Session, kind: MediaKind, ref_id, stats: SyncStats,
) -> None:
    """If *arr says no file for this record, mark any existing media_file missing."""
    rows = db.scalars(
        select(MediaFile).where(MediaFile.kind == kind, MediaFile.ref_id == ref_id)
    ).all()
    for mf in rows:
        if mf.scan_state != ScanState.missing:
            mf.scan_state = ScanState.missing
            stats.files_missing += 1


# ---------------------------------------------------------------------------
# Single-record webhook refreshers
# ---------------------------------------------------------------------------
def refresh_movie(db: Session, radarr_id: int, stats: Optional[SyncStats] = None) -> Optional[Movie]:
    """Pass `stats`, then call `schedule_pending_enrichment(stats)` after the commit."""
    if not arr_settings.configured("radarr"):
        return None
    with RadarrClient(*arr_settings.creds("radarr")) as rc:
        payload = rc.get_movie(radarr_id)
    stats = stats if stats is not None else SyncStats()
    return _upsert_movie(db, payload, stats)


def refresh_series(db: Session, sonarr_id: int) -> Optional[Series]:
    if not arr_settings.configured("sonarr"):
        return None
    with SonarrClient(*arr_settings.creds("sonarr")) as sc:
        payload = sc.get_series(sonarr_id)
        stats = SyncStats()
        series = _upsert_series(db, payload, stats)
        episodes = sc.list_episodes(sonarr_id)
        episode_files = sc.list_episode_files(sonarr_id)
        files_by_id = {f["id"]: f for f in episode_files}
        for ep_payload in episodes:
            season_num = ep_payload.get("seasonNumber")
            if season_num is None:
                continue
            existing_season = db.scalar(
                select(Season).where(
                    Season.series_id == series.id,
                    Season.season_number == season_num,
                )
            )
            if existing_season is None:
                db.add(Season(series_id=series.id, season_number=season_num))
                db.flush()
            _upsert_episode(db, series, ep_payload, files_by_id, stats)
    return series


def rescan_series(db: Session, sonarr_id: int) -> Optional[Series]:
    """Reconcile a series folder with Sonarr, then pull updated state.

    Intended for the case where the user dropped a file into the series
    folder outside Sonarr's import pipeline. Two-step flow, because one
    Sonarr command alone doesn't cover it:

        1. RescanSeries: refreshes Sonarr's EpisodeFile rows against disk.
           Flips hasFile=False on files that vanished, but does NOT import
           brand-new files.
        2. ManualImport: GET /api/v3/manualimport walks the series folder,
           parses filenames, and returns candidate (path, episodeIds, quality)
           tuples. We drop any candidate with a non-empty `rejections` list
           or without at least one parsed episode (Sonarr won't import those
           anyway), then POST ManualImport with importMode=Auto to let
           Sonarr slot the files under the right episodes.
        3. refresh_series: pulls the resulting state into F7FIVE0.

    DownloadedEpisodesScan is NOT used: Sonarr explicitly rejects any path
    that maps to an existing series folder, so it would no-op on the case
    this function exists to solve.

    The caller is responsible for committing. Raises ArrClientError on
    unrecoverable Sonarr failures; transient poll failures are swallowed
    so refresh_series still runs.
    """
    if not arr_settings.configured("sonarr"):
        return None

    with SonarrClient(*arr_settings.creds("sonarr")) as sc:
        # Step 1: reconcile known files against disk.
        rescan_envelope = sc.rescan_series(sonarr_id)
        _wait_for_sonarr_command(
            sc, rescan_envelope, label=f"rescan sonarr_id={sonarr_id}",
        )

        # Step 2: ask Sonarr to parse the folder and auto-import new files.
        try:
            series_payload = sc.get_series(sonarr_id)
        except ArrClientError:
            log.exception("sonarr get_series failed for sonarr_id=%s", sonarr_id)
            series_payload = {}
        series_path = series_payload.get("path")

        if series_path:
            try:
                candidates = sc.manual_import_candidates(
                    folder=series_path,
                    series_id=sonarr_id,
                    filter_existing_files=True,
                )
            except ArrClientError:
                log.exception(
                    "sonarr manualimport list failed for sonarr_id=%s path=%s",
                    sonarr_id, series_path,
                )
                candidates = []

            importable = [_manual_import_spec(c) for c in candidates if _is_importable(c)]
            skipped = len(candidates) - len(importable)
            log.info(
                "sonarr manualimport sonarr_id=%s path=%s candidates=%d importable=%d "
                "skipped=%d",
                sonarr_id, series_path, len(candidates), len(importable), skipped,
            )
            if importable:
                try:
                    mi_envelope = sc.manual_import_command(importable, import_mode="Auto")
                    _wait_for_sonarr_command(
                        sc, mi_envelope,
                        label=f"manualimport sonarr_id={sonarr_id}",
                        timeout_sec=_MANUAL_IMPORT_POLL_TIMEOUT_SEC,
                    )
                except ArrClientError:
                    log.exception(
                        "sonarr manualimport command failed for sonarr_id=%s", sonarr_id,
                    )
        else:
            log.warning(
                "sonarr sonarr_id=%s has no path; skipping manualimport step",
                sonarr_id,
            )

    return refresh_series(db, sonarr_id)


def _wait_for_sonarr_command(
    sc: "SonarrClient",
    envelope: Any,
    *,
    label: str,
    timeout_sec: float = _RESCAN_POLL_TIMEOUT_SEC,
) -> None:
    """Block until a Sonarr command reaches a terminal status. Transient
    poll errors are swallowed; timeout logs a warning but returns so the
    caller can proceed (refresh_series will still pick up whatever landed)."""
    command_id = envelope.get("id") if isinstance(envelope, dict) else None
    if command_id is None:
        return
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            state = sc.get_command(command_id)
        except ArrClientError:
            time.sleep(_RESCAN_POLL_INTERVAL_SEC)
            continue
        status = (state or {}).get("status", "").lower()
        if status in ("completed", "failed", "aborted"):
            log.info("sonarr %s command=%s status=%s", label, command_id, status)
            return
        time.sleep(_RESCAN_POLL_INTERVAL_SEC)
    log.warning(
        "sonarr %s command=%s did not finish within %ds; continuing anyway",
        label, command_id, int(timeout_sec),
    )


def _is_importable(candidate: dict[str, Any]) -> bool:
    """Sonarr returns every parsed file plus rejection metadata. We only
    auto-import entries that parsed cleanly AND mapped to at least one
    episode; anything else would need manual operator attention on the
    Sonarr side and we shouldn't silently guess on their behalf."""
    if candidate.get("rejections"):
        return False
    episodes = candidate.get("episodes") or []
    if not episodes:
        return False
    return bool(candidate.get("path"))


def _manual_import_spec(candidate: dict[str, Any]) -> dict[str, Any]:
    """Trim a manualimport candidate down to the fields the ManualImport
    command requires. Pulled straight from the GET response so we don't
    guess at quality/languages, since Sonarr already did the parse."""
    spec: dict[str, Any] = {
        "path": candidate["path"],
        "seriesId": (candidate.get("series") or {}).get("id"),
        "episodeIds": [e.get("id") for e in (candidate.get("episodes") or []) if e.get("id")],
        "quality": candidate.get("quality"),
        "languages": candidate.get("languages") or [],
    }
    if candidate.get("releaseGroup"):
        spec["releaseGroup"] = candidate["releaseGroup"]
    if candidate.get("indexerFlags") is not None:
        spec["indexerFlags"] = candidate["indexerFlags"]
    if candidate.get("episodeFileId"):
        spec["episodeFileId"] = candidate["episodeFileId"]
    return spec


def refresh_artist(db: Session, lidarr_id: int, stats: Optional[SyncStats] = None) -> Optional[Artist]:
    """Pass `stats`, then call `schedule_pending_enrichment(stats)` after the commit."""
    if not arr_settings.configured("lidarr"):
        return None
    with LidarrClient(*arr_settings.creds("lidarr")) as lc:
        payload = lc.get_artist(lidarr_id)
        stats = stats if stats is not None else SyncStats()
        artist = _upsert_artist(db, payload, stats)
        track_files = lc.list_track_files(lidarr_id)
        files_by_id = {f["id"]: f for f in track_files}
        albums = lc.list_albums(lidarr_id)
        for alb_payload in albums:
            album = _upsert_album(db, artist, alb_payload, stats)
            alb_id = alb_payload.get("id")
            if alb_id is None:
                continue
            tracks = lc.list_tracks(alb_id)
            for trk_payload in tracks:
                _upsert_track(db, album, trk_payload, files_by_id, stats)
    return artist


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def _genres(payload: dict[str, Any]) -> list[str]:
    """Pull a clean list of genre strings off a Lidarr artist or album
    payload. Empty when source omits the field. Strips blanks so we
    don't surface '' in the UI."""
    raw = payload.get("genres") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for g in raw:
        if isinstance(g, str):
            s = g.strip()
            if s:
                out.append(s)
    return out


def _image_url(images: list[dict[str, Any]], cover_type: str) -> Optional[str]:
    for img in images:
        if img.get("coverType", "").lower() == cover_type.lower():
            remote = img.get("remoteUrl")
            if remote:
                return remote
            # Lidarr's "url" field is a local filesystem path when
            # remoteUrl is absent.  Only use it if it looks like a URL.
            local = img.get("url") or ""
            if local.startswith("http"):
                return local
            return None
    return None


def _throttle_after(
    result: Optional[ArtOverride], *, throttle: bool,
) -> None:
    """Sleep the configured inter-image delay after a successful download.

    Skips the sleep when nothing was fetched (None result) or when the
    caller flagged throttle=False (webhook-triggered single-entity sync,
    where one extra image doesn't merit pacing). Best-effort: a result
    representing an existing row that wasn't re-downloaded still sleeps,
    which is fine since the sleep is upper-bounded by the sync interval.
    """
    if not throttle or result is None:
        return
    if settings.art_download_delay_ms <= 0:
        return
    time.sleep(settings.art_download_delay_ms / 1000.0)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp. Accepts trailing Z."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _ms_to_seconds(value) -> Optional[int]:
    """Lidarr durations are milliseconds; Sonarr runtime is sometimes a
    'HH:MM:SS' string. Best-effort convert to seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 10000:  # heuristically milliseconds
            return int(value / 1000)
        return int(value)
    if isinstance(value, str):
        parts = value.split(":")
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return None
        if len(parts) == 3:
            h, m, s = parts
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = parts
            return m * 60 + s
        if len(parts) == 1:
            return parts[0]
    return None


def _nullify_sentinel(value):
    """Treat *arr sentinel values (0 for ints, '' / '0' / '00000000-0000-0000-0000-000000000000'
    for strings) as missing metadata. Returning None lets many unmapped rows
    coexist under a UNIQUE constraint (Postgres allows multiple NULLs) and
    stops the 'fallback lookup by external id' from silently merging them."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value  # leave booleans alone
    if isinstance(value, (int, float)):
        return None if value == 0 else value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s == "0":
            return None
        if s.lower() == "00000000-0000-0000-0000-000000000000":
            return None
        return s
    return value


def _safe_int(value) -> Optional[int]:
    """Coerce a payload value to int. Strips leading non-digits (vinyl side
    prefixes like 'A1' → 1). Returns None if nothing numeric is present."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        # Handle pure int strings first.
        try:
            return int(s)
        except ValueError:
            pass
        # Fall back to pulling the first run of digits (e.g. 'A1' → 1).
        digits = ""
        started = False
        for ch in s:
            if ch.isdigit():
                digits += ch
                started = True
            elif started:
                break
        try:
            return int(digits) if digits else None
        except ValueError:
            return None
    return None


def _first_int(value) -> Optional[int]:
    """audioChannels sometimes comes in as '5.1' or '2'. Take the leading int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = ""
        for ch in value:
            if ch.isdigit():
                digits += ch
            else:
                break
        try:
            return int(digits) if digits else None
        except ValueError:
            return None
    return None
