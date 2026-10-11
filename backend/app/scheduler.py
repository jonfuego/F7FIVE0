"""APScheduler bootstrap for the F7FIVE0 API process.

One BackgroundScheduler per process. Started from the FastAPI lifespan,
shut down on app exit. Jobs run with their own DB session via `db_session()`.
"""
from __future__ import annotations

import logging
import random
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db import SessionLocal, db_session
from app.services import (
    library_folders, live_hub, nas_auth, scan_library, scan_music_videos, scan_status, sync, updates,
)


log = logging.getLogger("f7five0.scheduler")

_scheduler: Optional[BackgroundScheduler] = None

# Job id constants so we can add/remove idempotently.
JOB_FULL_SYNC = "arr_full_sync"
JOB_MUSIC_VIDEOS_SCAN = "music_videos_scan"
JOB_FOLDER_SCAN = "folder_scan"
JOB_AUDIO_ANALYSIS = "audio_analysis"
JOB_UPDATE_CHECK = "update_check"
JOB_ART_COPIES = "art_copies_backfill"
JOB_MOVIE_GENRES = "movie_genres_backfill"
JOB_ARTIST_ART = "artist_art_autofill"

# Once a day, give or take an hour, so a fleet of servers doesn't hit GitHub
# at the same second. Checking never installs anything.
UPDATE_CHECK_JITTER_SEC = 3600

# Defer enrichment a few seconds. Callers schedule it only after the row's
# transaction has committed (the scan and the *arr sync both do); the delay is
# a spacing, not what makes the row visible.
ENRICH_DELAY_SEC = 5

# Gap after each movie the genres backfill has to look up at TMDB.
MOVIE_GENRES_PAUSE_SEC = 0.25

# One folder scan at a time in this process: the periodic job, the ad hoc job
# (Admin, folder save) and a manual start can all be queued together.
_folder_scan_lock = threading.Lock()

# One artist art auto-fill run at a time, even if a queued run starts while
# the previous one is still walking artists.
_artist_art_lock = threading.Lock()


def _run_full_sync() -> None:
    """Scheduler-invoked wrapper around sync.full_sync. Owns its own session."""
    stats = None
    try:
        with db_session() as db:
            stats = sync.full_sync(db)
    except Exception:
        log.exception("scheduled full_sync raised")
        return
    # The session has committed; the rows are visible to the enrichment jobs.
    sync.schedule_pending_enrichment(stats)


def _run_music_videos_scan() -> None:
    """Scheduler-invoked wrapper around the music-videos filesystem scan.
    Owns its own session and writes its status block as it goes (the file total
    up front, then a running count at every batch, then the finished time), the
    same way the folder scan does. The walk touches the NAS on every iteration
    so callers should not block on it."""
    error = None
    stats = None
    db = SessionLocal()
    try:
        scan_status.mv_begin(db, force=True)
        db.commit()

        def progress(st, err=None):
            # Save the rows found so far together with the status, so Admin's
            # count never runs ahead of what the library holds.
            scan_status.mv_progress(db, st, err)
            db.commit()

        # Connect any saved NAS sign-ins before walking folders, so a UNC
        # share is readable for this scan. Cheap when already connected.
        nas_auth.ensure_all(db)
        stats = scan_music_videos.scan(db, on_progress=progress)
        db.commit()
    except Exception as exc:
        log.exception("music_videos scan raised")
        db.rollback()
        error = f"The scan stopped: {exc}"
    finally:
        try:
            scan_status.mv_finish(db, stats, error)
            db.commit()
        except Exception:
            log.exception("could not record the end of the music_videos scan")
            db.rollback()
        db.close()
        # New videos mean new artists; give the ones with no picture one.
        trigger_artist_art_autofill(delay_sec=ENRICH_DELAY_SEC)


def _scan_folders() -> bool:
    """One pass over the library folders. The scan saves as it goes (every
    batch and at the end of each library, see scan_library), so this owns its
    session and does not wrap the pass in one commit-on-exit block. Admin's
    scan status is written along the way. Returns whether a music-videos
    folder is configured."""
    has_music_videos = False
    error = None
    db = SessionLocal()
    try:
        scan_status.begin(db, force=True)
        db.commit()

        def progress(label, state, stats, err=None):
            scan_status.set_library(db, label, state, stats, err)

        # Connect any saved NAS sign-ins before walking folders, so a UNC
        # share is readable for this scan. Cheap when already connected.
        nas_auth.ensure_all(db)
        scan_library.scan_all(db, on_progress=progress)
        has_music_videos = bool(library_folders.folders(db, "music_videos"))
        db.commit()
        # Everything is saved: re-queue enrichment for rows that missed it.
        try:
            scan_library.schedule_catch_up(db)
        except Exception:
            log.exception("enrichment catch-up raised")
        # Movies that were matched but enriched before genres were saved.
        trigger_movie_genres_backfill(delay_sec=ENRICH_DELAY_SEC)
        # Artists the scan just added that have no picture of their own.
        trigger_artist_art_autofill(delay_sec=ENRICH_DELAY_SEC)
    except Exception as exc:
        log.exception("folder scan raised")
        db.rollback()
        error = f"The scan stopped: {exc}"
    finally:
        try:
            scan_status.finish(db, error)
            db.commit()
        except Exception:
            log.exception("could not record the end of the folder scan")
            db.rollback()
        db.close()
    return has_music_videos


def _run_folder_scan() -> None:
    """Scan the libraries that have no *arr (movies / TV / music folders),
    then the music-videos folder when one is configured. Finally kick off one
    low-priority audio-analysis step so new music gets loudness / waveform /
    similarity filled in without an operator running the CLI."""
    if not _folder_scan_lock.acquire(blocking=False):
        log.info("a folder scan is already running; skipping this one")
        return
    try:
        has_music_videos = _scan_folders()
    finally:
        _folder_scan_lock.release()
    if has_music_videos:
        _run_music_videos_scan()
    # One harmless real live-channel event, proving the hub end to end: the
    # library scan finished. Connected web/app clients can refresh instead of
    # waiting for their next poll. Fire-and-forget; a publish with no listeners
    # is a no-op (see services/live_hub).
    try:
        live_hub.publish("library.scan_finished", {"music_videos": has_music_videos})
    except Exception:
        log.exception("publishing library.scan_finished raised")
    # Audio analysis runs AFTER the scan so freshly imported tracks are in the
    # working set. It only ever processes one track per step and reschedules
    # itself, so it stays low-priority and never blocks the scan path.
    _kick_audio_analysis()


def _run_update_check() -> None:
    """Scheduler-invoked check of GitHub for a newer release. Stores the answer
    for Admin > Updates (and its nav badge); a network failure is stored, not
    raised. It never starts an update."""
    try:
        with db_session() as db:
            updates.check_for_update(db)
    except Exception:
        log.exception("scheduled update check raised")


def _run_art_copies_backfill() -> None:
    """One-shot after boot: build the 300 / 600 px copies for art saved before
    they existed. Batched and paced, own session, never raises; a rerun creates
    nothing new (see art.backfill_art_copies)."""
    try:
        from app.services import art as art_service
        with db_session() as db:
            made = art_service.backfill_art_copies(db, pause_sec=0.2)
        log.info("art copies backfill: %d created", made)
    except Exception:
        log.exception("art copies backfill raised")


def _run_movie_genres_backfill() -> None:
    """Fill genres for TMDB-matched movies that have none. Batched and paced,
    own session, never raises; a rerun saves nothing new (see
    runner.backfill_movie_genres). Does nothing while no TMDB key is set."""
    try:
        from app.services.metadata.runner import backfill_movie_genres
        with db_session() as db:
            filled = backfill_movie_genres(db, pause_sec=MOVIE_GENRES_PAUSE_SEC)
        log.info("movie genres backfill: %d filled", filled)
    except Exception:
        log.exception("movie genres backfill raised")


def trigger_movie_genres_backfill(delay_sec: int = 0) -> None:
    """Queue the movie genres backfill. One job id, so queuing it again (after
    each folder scan, after a TMDB key is saved) never stacks two runs. No-op
    when the scheduler is not running (CLI)."""
    if _scheduler is None:
        return
    _scheduler.add_job(
        _run_movie_genres_backfill,
        id=JOB_MOVIE_GENRES,
        name="fill movie genres from TMDB",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=delay_sec),
    )


def _run_artist_art_autofill() -> None:
    """Give artists that have no thumb art one from TheAudioDB or Deezer.
    Batched and paced, own session, never raises; a rerun creates nothing new
    (see artist_art_autofill). Skips quietly if a run is already going."""
    if not _artist_art_lock.acquire(blocking=False):
        log.info("artist art auto-fill already running; skipping this one")
        return
    try:
        from app.services.artist_art_autofill import autofill_artist_art
        with db_session() as db:
            filled = autofill_artist_art(db)
        log.info("artist art auto-fill: %d filled", filled)
    except Exception:
        log.exception("artist art auto-fill raised")
    finally:
        _artist_art_lock.release()


def trigger_artist_art_autofill(delay_sec: int = 0) -> None:
    """Queue the artist art auto-fill. One job id, so queuing it again (after
    each music scan and music videos scan) never stacks two runs. No-op when
    the scheduler is not running (CLI)."""
    if _scheduler is None:
        return
    _scheduler.add_job(
        _run_artist_art_autofill,
        id=JOB_ARTIST_ART,
        name="fill missing artist pictures",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=delay_sec),
    )


def _run_audio_analysis_step() -> None:
    """Analyze ONE un-analyzed track, then reschedule the next step.

    Low-priority, strictly one track at a time: the job finds the first track
    with no `track_audio_analysis` row, runs the SHARED analysis engine on it
    (the same `services.audio_analysis` code the `analyze-audio` CLI uses),
    recomputes that track's album gain and similarity edges, commits, and
    queues the next step a short delay later. When nothing is left it stops, so
    an idle library costs nothing. A later folder scan re-arms it for new music.
    """
    try:
        from app.services import audio_analysis as aa
        with db_session() as db:
            pending = aa.tracks_needing_analysis(db)
            if not pending:
                log.info("audio analysis: nothing to do")
                return
            tid = pending[0]
            status = aa.analyze_track(db, tid)
            db.commit()
            if status == aa.STATUS_ANALYZED:
                aa.recompute_album_gains(db, [tid])
                db.commit()
                aa.rebuild_similarity(db, [tid])
                db.commit()
            log.info("audio analysis step: track %s -> %s (%d left)",
                     tid, status, max(0, len(pending) - 1))
    except Exception:
        log.exception("audio analysis step raised")
        return
    # Queue the next track. A short gap keeps the box responsive during a long
    # first-install backfill (the equivalent of the CLI's --throttle).
    _kick_audio_analysis(delay_sec=max(0, settings.audio_analysis_throttle_sec))


def _kick_audio_analysis(delay_sec: int = 0) -> None:
    """Schedule the next audio-analysis step. No-op when not running (CLI)."""
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    _scheduler.add_job(
        _run_audio_analysis_step,
        id=JOB_AUDIO_ANALYSIS,
        name="audio analysis (one track)",
        max_instances=1,       # never run two analysis steps at once
        coalesce=True,
        replace_existing=True,  # a second kick just moves the next run
        next_run_time=when,
    )


def trigger_audio_analysis_now() -> None:
    """Start the automatic audio-analysis walk now. Admin-initiated
    ("Analyze music now"). Idempotent: re-clicking just re-arms the walk."""
    if _scheduler is None:
        log.warning("trigger_audio_analysis_now called but scheduler not started")
        return
    _kick_audio_analysis()


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
    # Always registered: folders can be added from Admin > Library folders
    # after start, and a pass with nothing configured does nothing.
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
    sched.add_job(
        _run_update_check,
        trigger=IntervalTrigger(days=1, jitter=UPDATE_CHECK_JITTER_SEC),
        id=JOB_UPDATE_CHECK,
        name="check GitHub for a newer F7FIVE0",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        # First look a few minutes after boot (spread out a little), then daily.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=300 + random.randint(0, 300)),
    )
    # Runs once, a minute after boot, so startup is not delayed. Cheap on every
    # later boot (it only stats files that already have their copies).
    sched.add_job(
        _run_art_copies_backfill,
        id=JOB_ART_COPIES,
        name="build smaller poster copies",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    # Also once after boot, a bit later than the art job. Folder scans and a
    # saved TMDB key queue it again (same job id, so it never stacks).
    sched.add_job(
        _run_movie_genres_backfill,
        id=JOB_MOVIE_GENRES,
        name="fill movie genres from TMDB",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
    )
    # And once more after boot, after the art-copies and genres jobs. Each
    # music and music videos scan queues it again (same job id).
    sched.add_job(
        _run_artist_art_autofill,
        id=JOB_ARTIST_ART,
        name="fill missing artist pictures",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=120),
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
    _scheduler.add_job(_run_folder_scan, id=f"{JOB_FOLDER_SCAN}_adhoc", replace_existing=True)


def trigger_folder_scan_now() -> None:
    """Scan the library folders now (after Admin > Library folders changes)."""
    if _scheduler is None:
        log.warning("trigger_folder_scan_now called but scheduler not started")
        return
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


def schedule_enrich_movie(movie_id: uuid.UUID, delay_sec: float = ENRICH_DELAY_SEC) -> None:
    """Defer an enrich_movie call by `delay_sec` (ENRICH_DELAY_SEC by default).
    Only call it for a row that is already committed. No-op when the scheduler
    isn't running (e.g., during a CLI invocation)."""
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    _scheduler.add_job(
        _run_enrich_movie,
        args=[movie_id],
        id=f"enrich_movie_{movie_id}",
        replace_existing=True,
        next_run_time=when,
    )


def schedule_enrich_artist(artist_id: uuid.UUID, delay_sec: float = ENRICH_DELAY_SEC) -> None:
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    _scheduler.add_job(
        _run_enrich_artist,
        args=[artist_id],
        id=f"enrich_artist_{artist_id}",
        replace_existing=True,
        next_run_time=when,
    )


def schedule_enrich_album(album_id: uuid.UUID, delay_sec: float = ENRICH_DELAY_SEC) -> None:
    if _scheduler is None:
        return
    when = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
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
