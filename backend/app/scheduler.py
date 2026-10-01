"""APScheduler bootstrap for the F7FIVE0 API process.

One BackgroundScheduler per process. Started from the FastAPI lifespan,
shut down on app exit. Jobs run with their own DB session via `db_session()`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db import db_session
from app.services import scan_library, scan_music_videos, sync


log = logging.getLogger("f7five0.scheduler")

_scheduler: Optional[BackgroundScheduler] = None

# Job id constants so we can add/remove idempotently.
JOB_FULL_SYNC = "arr_full_sync"
JOB_MUSIC_VIDEOS_SCAN = "music_videos_scan"
JOB_FOLDER_SCAN = "folder_scan"

# Defer enrichment far enough that the upsert transaction is committed
# before the worker reads the row. Five seconds matches the spec.
ENRICH_DELAY_SEC = 5


def _run_full_sync() -> None:
    """Scheduler-invoked wrapper around sync.full_sync. Owns its own session."""
    try:
        with db_session() as db:
            sync.full_sync(db)
    except Exception:
        log.exception("scheduled full_sync raised")


def _run_music_videos_scan() -> None:
    """Scheduler-invoked wrapper around the music-videos filesystem scan.
    Owns its own session. The walk touches the NAS on every iteration so
    callers should not block on it."""
    try:
        with db_session() as db:
            scan_music_videos.scan(db)
    except Exception:
        log.exception("music_videos scan raised")


def _run_folder_scan() -> None:
    """Scan the libraries that have no *arr (movies / TV / music folders),
    then the music-videos folder when one is configured."""
    try:
        with db_session() as db:
            scan_library.scan_all(db)
    except Exception:
        log.exception("folder scan raised")
    if settings.library_root_music_videos:
        _run_music_videos_scan()


def _run_series_rescan(sonarr_id: int) -> None:
    """Scheduler-invoked wrapper around sync.rescan_series. Owns its own
    session so the API request that triggered it can return 202 without
    waiting on Sonarr's command to finish."""
    try:
        with db_session() as db:
            sync.rescan_series(db, sonarr_id)
    except Exception:
        log.exception("series rescan raised for sonarr_id=%s", sonarr_id)


def start() -> BackgroundScheduler:
    """Start the scheduler if not already running. Idempotent."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        _run_full_sync,
        trigger=IntervalTrigger(minutes=5),
        id=JOB_FULL_SYNC,
        name="*arr full sync",
        max_instances=1,           # never stack two syncs
        coalesce=True,             # collapse missed fires
        replace_existing=True,
        next_run_time=None,        # don't kick one off immediately on boot
    )
    if scan_library.any_enabled() or settings.library_root_music_videos:
        sched.add_job(
            _run_folder_scan,
            trigger=IntervalTrigger(minutes=max(5, settings.folder_scan_interval_minutes)),
            id=JOB_FOLDER_SCAN,
            name="library folder scan",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            # First pass shortly after boot so a fresh install fills up
            # without waiting a full interval.
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
    sched.start()
    _scheduler = sched
    log.info("scheduler started (full_sync every 5 minutes)")
    return sched


def shutdown(wait: bool = False) -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=wait)
    except Exception:
        log.exception("scheduler shutdown raised")
    _scheduler = None
    log.info("scheduler stopped")


def trigger_full_sync_now() -> None:
    """Fire a full sync immediately (out of band). Useful for admin endpoints."""
    if _scheduler is None:
        log.warning("trigger_full_sync_now called but scheduler not started")
        return
    _scheduler.add_job(_run_full_sync, id=f"{JOB_FULL_SYNC}_adhoc", replace_existing=True)
    if scan_library.any_enabled():
        _scheduler.add_job(_run_folder_scan, id=f"{JOB_FOLDER_SCAN}_adhoc", replace_existing=True)


def trigger_music_videos_scan_now() -> None:
    """Fire a music-videos filesystem scan immediately. Admin-initiated."""
    if _scheduler is None:
        log.warning("trigger_music_videos_scan_now called but scheduler not started")
        return
    _scheduler.add_job(
        _run_music_videos_scan,
        id=f"{JOB_MUSIC_VIDEOS_SCAN}_adhoc",
        replace_existing=True,
    )


def _run_enrich_movie(movie_id: uuid.UUID) -> None:
    try:
        from app.services.metadata.runner import enrich_movie
        with db_session() as db:
            enrich_movie(db, movie_id)
    except Exception:
        log.exception("enrich_movie raised for movie_id=%s", movie_id)


def _run_enrich_artist(artist_id: uuid.UUID) -> None:
    try:
        from app.services.metadata.runner import enrich_artist
        with db_session() as db:
            enrich_artist(db, artist_id)
    except Exception:
        log.exception("enrich_artist raised for artist_id=%s", artist_id)


def _run_enrich_album(album_id: uuid.UUID) -> None:
    try:
        from app.services.metadata.runner import enrich_album
        with db_session() as db:
            enrich_album(db, album_id)
    except Exception:
        log.exception("enrich_album raised for album_id=%s", album_id)


def schedule_enrich_movie(movie_id: uuid.UUID) -> None:
    """Defer an enrich_movie call by ENRICH_DELAY_SEC. No-op when the
    scheduler isn't running (e.g., during a CLI invocation)."""
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=ENRICH_DELAY_SEC)
    _scheduler.add_job(
        _run_enrich_movie,
        args=[movie_id],
        id=f"enrich_movie_{movie_id}",
        replace_existing=True,
        next_run_time=when,
    )


def schedule_enrich_artist(artist_id: uuid.UUID) -> None:
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=ENRICH_DELAY_SEC)
    _scheduler.add_job(
        _run_enrich_artist,
        args=[artist_id],
        id=f"enrich_artist_{artist_id}",
        replace_existing=True,
        next_run_time=when,
    )


def schedule_enrich_album(album_id: uuid.UUID) -> None:
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=ENRICH_DELAY_SEC)
    _scheduler.add_job(
        _run_enrich_album,
        args=[album_id],
        id=f"enrich_album_{album_id}",
        replace_existing=True,
        next_run_time=when,
    )


def _run_marker_analysis(series_id: Optional[uuid.UUID], force: bool) -> None:
    """Scheduler-invoked intro/credits analysis. Owns its own session and
    runs one ffmpeg at a time so live streams keep NVENC headroom."""
    try:
        from app.services import markers
        with db_session() as db:
            markers.analyze_episode_files(db, series_id=series_id, force=force)
    except Exception:
        log.exception("marker analysis raised (series_id=%s)", series_id)


def trigger_marker_analysis_now(
    series_id: Optional[uuid.UUID] = None, force: bool = False,
) -> None:
    """Fire an intro/credits analysis pass out of band. Admin-initiated.
    Scoped per series_id so re-triggering one series replaces its job."""
    if _scheduler is None:
        log.warning("trigger_marker_analysis_now called but scheduler not started")
        return
    suffix = str(series_id) if series_id else "all"
    _scheduler.add_job(
        _run_marker_analysis,
        args=[series_id, force],
        id=f"marker_analysis_{suffix}",
        replace_existing=True,
    )


def trigger_series_rescan_now(sonarr_id: int) -> None:
    """Fire a RescanSeries + refresh_series flow for one series. Scoped per
    sonarr_id so simultaneous rescans of different series run in parallel;
    a second click on the same series replaces the in-flight job."""
    if _scheduler is None:
        log.warning("trigger_series_rescan_now called but scheduler not started")
        return
    _scheduler.add_job(
        _run_series_rescan,
        args=[sonarr_id],
        id=f"series_rescan_{sonarr_id}",
        replace_existing=True,
    )
