"""F7FIVE0 Stream Gateway.

Separate FastAPI app so streaming load doesn't starve browse calls.

Run locally:
    uvicorn app.stream:app --host 127.0.0.1 --port 8002 --reload

Auth model: every endpoint validates an HMAC-signed URL inline. The main
API issues the URL after a JWT-authenticated /api/stream/start call; from
then on the gateway sees only the signed params. No JWT here.

Concurrency: this service must run as a single uvicorn worker. The
transcoder manager keeps ffmpeg process handles in-process; multiple
workers would each spawn their own ffmpeg for the same session and lose
kill authority across worker boundaries. See install-services.ps1.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.media_file import MediaFile, ScanState
from app.models.transcode import TranscodeSession
from app.services import library_folders, nas_auth, transcode_cache, transcoder
from app.services.path_map import translate as translate_path
from app.services.playback import (
    VARIANT_LADDER,
    is_audio_only,
    pick_variants,
    single_rung_for_cpu,
)
from app.services.range_response import ensure_under_roots, serve_file_range
from app.services.security import verify_stream_url_params
from app.services.signed_urls import session_authorizes
from app.services.trusted_proxy import real_client_ip
from app.services.track_opts import TrackOptsError, parse_token


logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("f7five0.stream")


CACHE_SWEEP_INTERVAL_MIN = 5


def _run_enforce_cap() -> None:
    """APScheduler target. Swallows exceptions so the scheduler keeps running."""
    try:
        freed = transcode_cache.enforce_cap()
        if freed > 0:
            log.info("LRU eviction freed %.1f MB", freed / 1_048_576)
    except Exception:
        log.exception("transcode_cache.enforce_cap raised")


def _close_orphaned_sessions() -> None:
    """Mark stale transcode_sessions rows ended on gateway boot.

    The transcoder session registry lives in-process. When this gateway
    starts, no ffmpeg from a prior process can still be running, so any
    row with ended_at IS NULL is an orphan from an unclean shutdown
    (service restart, crash, host reboot). Closing them here keeps the
    admin Active Streams view honest and prevents the row count from
    growing unbounded across deploys.
    """
    try:
        with SessionLocal() as db:
            result = db.execute(
                update(TranscodeSession)
                .where(TranscodeSession.ended_at.is_(None))
                .values(ended_at=datetime.now(timezone.utc))
            )
            db.commit()
            count = result.rowcount or 0
            if count:
                log.info("closed %d orphaned transcode_sessions row(s) on startup", count)
    except Exception:
        log.exception("orphan session sweep raised")


# ---------------------------------------------------------------------------
# Lifespan: start/stop the transcode janitor + LRU sweeper with the app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("F7FIVE0 Stream Gateway starting (env=%s)", settings.environment)
    Path(settings.transcode_cache_dir).mkdir(parents=True, exist_ok=True)
    # Connect saved NAS sign-ins in this process's own logon session. The
    # stream gateway is a separate process from the API, so it must do its own
    # connect; LocalSystem services share a session but a -ServiceUser one does
    # not. Cheap when already connected; a no-op off Windows.
    try:
        nas_auth.ensure_all()
    except Exception:
        log.warning("NAS ensure_all at stream startup raised", exc_info=True)
    _close_orphaned_sessions()
    transcoder.manager.start_janitor()

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        _run_enforce_cap,
        trigger=IntervalTrigger(minutes=CACHE_SWEEP_INTERVAL_MIN),
        id="transcode_cache_enforce_cap",
        name="LRU eviction",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    sched.start()
    app.state.cache_scheduler = sched
    log.info("LRU eviction scheduled every %d minutes", CACHE_SWEEP_INTERVAL_MIN)

    yield

    log.info("F7FIVE0 Stream Gateway shutting down")
    try:
        sched.shutdown(wait=False)
    except Exception:
        log.exception("cache scheduler shutdown raised")
    transcoder.manager.stop()


app = FastAPI(
    title="F7FIVE0 Stream Gateway",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
#
# CORS: the Cast receiver (Styled Media Receiver, sandboxed Chromium) fetches
# HLS playlists and segments with no credentials, and browsers enforce CORS
# on those fetches. The signed URL itself is the authorization; there's no
# cookie or Authorization header on these requests, so credentialed CORS is
# not needed. Allow all origins, expose Content-Length / Content-Range /
# Accept-Ranges so media engines can compute progress and pick a byte-range
# strategy. Without `Range` in the allowed headers list, preflights from
# receivers that send Range on GET (rare but possible) would fail.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["Range", "If-Modified-Since", "If-None-Match"],
    expose_headers=[
        "Accept-Ranges",
        "Content-Length",
        "Content-Range",
        "Content-Type",
    ],
    max_age=600,
)


@app.middleware("http")
async def client_ip_middleware(request: Request, call_next):
    # SEC-P1-1: honour CF-Connecting-IP / X-Forwarded-For only from a trusted
    # proxy peer so a direct caller cannot spoof the IP we log.
    request.state.client_ip = real_client_ip(request)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Shared dependencies
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _allowed_roots(db: Session) -> list[Path]:
    """Every directory a media file is allowed to live under.

    Derived from the active library-folder configuration (the `libraries`
    table once Admin saves folders, else the `LIBRARY_ROOT_*` env keys), plus
    any explicit `STREAM_ALLOWED_ROOTS` entries. Each configured folder is
    added in both its raw form and its path-rewritten form (drive letter ->
    UNC) so a root matches whichever shape `media_files.path` was stored in.
    Returns an empty list only when nothing is configured; callers fail closed
    on that.
    """
    roots: list[Path] = []

    def _add(p: str) -> None:
        p = (p or "").strip()
        if not p:
            return
        roots.append(Path(p))
        translated = translate_path(p)
        if translated and translated != p:
            roots.append(Path(translated))

    for paths in library_folders.all_folders(db).values():
        for p in paths:
            _add(p)
    for p in (settings.stream_allowed_roots or "").split(";"):
        _add(p)
    return roots


def _contain(db: Session, path: Path) -> Path:
    """Enforce root containment, or bypass it only under the explicit,
    off-by-default unsafe development flag. With the flag off and no roots
    configured, every file is rejected (SEC-P0-4 fail closed)."""
    if settings.stream_unsafe_allow_any_path:
        log.warning(
            "stream_unsafe_allow_any_path is ON: serving %s without root "
            "containment. Never use this on a reachable install.", path,
        )
        return path.resolve(strict=False)
    return ensure_under_roots(path, _allowed_roots(db))


def verified_media_file(
    media_file_id: Annotated[uuid.UUID, PathParam()],
    db: Annotated[Session, Depends(get_db)],
    uid: Annotated[str, Query()],
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    t: Annotated[int, Query()] = 0,
    o: Annotated[str, Query()] = "",
    sid: Annotated[str, Query()] = "",
) -> MediaFile:
    """Validate the signed URL and return the `MediaFile` row.

    Raises 401 on bad signature, 403 on a revoked/expired session, 410 on
    missing, 409 on not-ready, 404 on unknown id. The HMAC check is done first
    so bad sigs never produce a DB lookup latency signal (SEC-P1-2: HMAC before
    DB). `t` is the HLS resume offset bucket (seconds); it and the issuing
    session id both participate in the HMAC payload so neither can be
    retargeted.
    """
    if t < 0:
        raise HTTPException(status_code=401, detail="bad_stream_signature")
    try:
        parse_token(o)
    except TrackOptsError:
        raise HTTPException(status_code=401, detail="bad_stream_signature")
    if not verify_stream_url_params(uid, str(media_file_id), exp, sig, sid,
                                    offset_bucket=t, opts=o):
        raise HTTPException(status_code=401, detail="bad_stream_signature")
    # SEC-P1-2: the signature checked out; now the issuing session must still be
    # live. This is the first DB touch, so a bad signature never reaches it.
    if not session_authorizes(db, sid):
        raise HTTPException(status_code=403, detail="session_revoked")

    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="media_file_not_found")
    if mf.scan_state == ScanState.missing:
        raise HTTPException(status_code=410, detail="file_missing")
    if mf.scan_state != ScanState.ready:
        raise HTTPException(status_code=409, detail="file_not_ready")
    return mf


def _signed_query(uid: str, mid: uuid.UUID, exp: int, sig: str, sid: str,
                  t: int = 0, o: str = "") -> str:
    params = {"uid": uid, "mid": str(mid), "exp": exp, "sig": sig, "t": t,
              "sid": sid}
    if o:
        params["o"] = o
    return urlencode(params)


def _variants_for(mf: MediaFile, o: str):
    """The source ladder, capped at the track-options quality ceiling.

    Without NVENC the master playlist carries a single rung (see
    playback.single_rung_for_cpu) so no player can start a second encode by
    switching quality on its own.

    Audio-only sources get one rung (the top rung's AAC bitrate; the label is
    only a cache key), since there is no picture to scale."""
    if is_audio_only(mf):
        return (VARIANT_LADDER[0],)
    variants = pick_variants(mf)
    max_h = parse_token(o).max_height
    if not settings.nvenc_enabled:
        return single_rung_for_cpu(variants, max_h)
    if max_h:
        capped = tuple(v for v in variants if v.height <= max_h)
        variants = capped or (variants[-1],)
    return variants


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/stream/health")
async def health():
    return {
        "status": "ok",
        "service": "f7five0-stream",
        "version": app.version,
    }


# ---------------------------------------------------------------------------
# Direct-play: MP4 byte-range straight from disk
# ---------------------------------------------------------------------------
@app.get("/stream/direct/{media_file_id}")
def direct_play(
    mf: Annotated[MediaFile, Depends(verified_media_file)],
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> object:
    path = _contain(db, Path(mf.path))

    # If the media lives on a UNC share that isn't reachable right now (common
    # after a reboot, before anything has touched the NAS), reconnect the saved
    # sign-in once and let the serve path try again. Cheap when connected.
    if nas_auth.is_unc_path(str(path)):
        try:
            os.stat(path)
        except OSError:
            nas_auth.ensure_all(db)

    container = (mf.container or "").lower()
    content_type: Optional[str] = None
    if container in {"mp4", "m4v", "mov"}:
        content_type = "video/mp4"
    elif container == "mkv":
        # Direct play of Matroska happens only when the client reported it can
        # play it (stream/start client_caps).
        content_type = "video/x-matroska"
    elif container == "webm":
        content_type = "video/webm"
    elif container == "mp3":
        content_type = "audio/mpeg"
    elif container == "m4a":
        # Apple's audio-in-MP4 container. audio/mp4 is the IANA-registered
        # type; audio/x-m4a is a common alias but less portable.
        content_type = "audio/mp4"
    elif container == "aac":
        content_type = "audio/aac"
    elif container == "wav":
        content_type = "audio/wav"
    elif container == "flac":
        content_type = "audio/flac"
    elif container in {"ogg", "oga"}:
        # Vorbis and some Opus files ride in Ogg. audio/ogg with a codecs
        # param would be more precise but browsers sniff the stream anyway.
        content_type = "audio/ogg"

    range_header = request.headers.get("range")
    log.info(
        "direct_play uid=%s mid=%s range=%s path=%s",
        request.query_params.get("uid"),
        mf.id,
        range_header or "-",
        mf.path,
    )
    return serve_file_range(path, range_header, content_type)


# ---------------------------------------------------------------------------
# HLS: master playlist
# ---------------------------------------------------------------------------
@app.get("/stream/hls/{media_file_id}/master.m3u8")
def hls_master(
    mf: Annotated[MediaFile, Depends(verified_media_file)],
    uid: Annotated[str, Query()],
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    t: Annotated[int, Query()] = 0,
    o: Annotated[str, Query()] = "",
    sid: Annotated[str, Query()] = "",
) -> PlainTextResponse:
    variants = _variants_for(mf, o)
    body = transcoder.build_master_playlist(
        mf.id, variants,
        signed_query=_signed_query(uid, mf.id, exp, sig, sid, t, o),
        audio_only=is_audio_only(mf),
    )
    return PlainTextResponse(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# HLS: variant playlist
# ---------------------------------------------------------------------------
_VARIANT_LABEL_RE = re.compile(r"^(high|medium|low)$")
_SEGMENT_NAME_RE = re.compile(r"^seg_(\d{5})\.ts$")


@app.get("/stream/hls/{media_file_id}/{variant}/index.m3u8")
def hls_variant_playlist(
    mf: Annotated[MediaFile, Depends(verified_media_file)],
    variant: Annotated[str, PathParam()],
    uid: Annotated[str, Query()],
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    db: Annotated[Session, Depends(get_db)],
    t: Annotated[int, Query()] = 0,
    o: Annotated[str, Query()] = "",
    sid: Annotated[str, Query()] = "",
) -> PlainTextResponse:
    if not _VARIANT_LABEL_RE.match(variant):
        raise HTTPException(status_code=404, detail="unknown_variant")
    v = transcoder.variant_by_label(variant)
    if v is None:
        raise HTTPException(status_code=404, detail="unknown_variant")

    source = _contain(db, Path(mf.path))

    try:
        user_id = uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad_uid")

    job = transcoder.manager.get_or_start(
        user_id=user_id,
        media_file_id=mf.id,
        variant=v,
        source_path=source,
        offset_bucket=t,
        opts=o,
        audio_only=is_audio_only(mf),
    )

    # Wait for ffmpeg to write the index. Early in a cold start ffmpeg has
    # not produced any segments yet; polling avoids a "manifest not found"
    # race on the very first playlist fetch.
    deadline = time.time() + transcoder.START_WAIT_SEC
    while not job.index_path.exists():
        if time.time() > deadline:
            raise HTTPException(status_code=503, detail="transcode_starting")
        if not job.is_running():
            raise HTTPException(
                status_code=500,
                detail=f"transcode_failed_rc_{job.returncode()}",
            )
        time.sleep(0.2)
    job.touch()

    body = job.index_path.read_text(encoding="utf-8")
    # Synthesize a VOD-typed playlist with EXT-X-ENDLIST for the encoded
    # output (source duration minus the resume offset_bucket). Without this
    # the Google Cast Default Media Receiver treats the EVENT playlist as
    # live and starts at the live edge. See [[fix-cast-live-edge]].
    output_duration = float((mf.duration_sec or 0) - t)
    if output_duration < 0.0:
        output_duration = 0.0
    rewritten = transcoder.rewrite_variant_playlist(
        body, mf.id, variant,
        signed_query=_signed_query(uid, mf.id, exp, sig, sid, t, o),
        duration_sec=output_duration,
    )
    return PlainTextResponse(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# HLS: keepalive
# ---------------------------------------------------------------------------
@app.get("/stream/keepalive/{media_file_id}")
def hls_keepalive(
    mf: Annotated[MediaFile, Depends(verified_media_file)],
    uid: Annotated[str, Query()],
    t: Annotated[int, Query()] = 0,
    o: Annotated[str, Query()] = "",
) -> Response:
    """Touch an existing transcode job so an open HLS player never trips the
    idle kill during a pause. This NEVER spawns: if no job exists (the encode
    already finished and was reaped, or the client is direct-playing) it is a
    no-op. The player pings this on its heartbeat while an HLS stream is
    mounted. The signed URL carries no variant (it is derived from the master
    URL), so touch whichever variant job is live for this (user, file, bucket).
    """
    try:
        user_id = uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad_uid")
    for variant_label in ("high", "medium", "low"):
        job = transcoder.manager.get(user_id, mf.id, variant_label, offset_bucket=t, opts=o)
        if job is not None:
            job.touch()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# HLS: segment
# ---------------------------------------------------------------------------
def segment_is_complete(out_dir: Path, seg_index: int) -> bool:
    """Whether `seg_{seg_index:05d}.ts` is fully written and safe to serve.

    ffmpeg's HLS muxer writes segments sequentially and only opens seg N+1
    after finalizing seg N, so the next segment existing proves this one is
    complete. The final segment has no successor, so we fall back to the
    `#EXT-X-ENDLIST` marker in the canonical playlist, which ffmpeg writes
    only when the encode finishes.
    """
    seg_path = out_dir / f"seg_{seg_index:05d}.ts"
    if not seg_path.exists():
        return False
    if (out_dir / f"seg_{seg_index + 1:05d}.ts").exists():
        return True
    index_path = out_dir / "index.m3u8"
    try:
        if index_path.exists() and "#EXT-X-ENDLIST" in index_path.read_text(encoding="utf-8"):
            return True
    except OSError:
        pass
    return False


@app.get("/stream/hls/{media_file_id}/{variant}/{segment}")
def hls_segment(
    mf: Annotated[MediaFile, Depends(verified_media_file)],
    variant: Annotated[str, PathParam()],
    segment: Annotated[str, PathParam()],
    uid: Annotated[str, Query()],
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    t: Annotated[int, Query()] = 0,
    o: Annotated[str, Query()] = "",
) -> object:
    if not _VARIANT_LABEL_RE.match(variant):
        raise HTTPException(status_code=404, detail="unknown_variant")
    seg_match = _SEGMENT_NAME_RE.match(segment)
    if not seg_match:
        raise HTTPException(status_code=404, detail="bad_segment_name")
    seg_index = int(seg_match.group(1))

    try:
        user_id = uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad_uid")

    range_header = request.headers.get("range")

    # Fast path: an already-complete segment is served straight from disk
    # without consulting or spawning a job, so a finished transcode is never
    # redundantly re-encoded. "Complete" means the next segment exists (ffmpeg
    # has moved on) or the playlist carries #EXT-X-ENDLIST. A partially written
    # .ts fails this gate and is never served. This returns before the first
    # manager.get, so a healthy stream touches the registry not at all.
    out_dir = transcoder.out_dir_for(mf.id, variant, t, o)
    if segment_is_complete(out_dir, seg_index):
        return serve_file_range(out_dir / segment, range_header, content_type="video/mp2t")

    # Segment missing or still being written: consult the registry, and only
    # then re-spawn.
    job = transcoder.manager.get(user_id, mf.id, variant, offset_bucket=t, opts=o)
    if job is None:
        # The session was evicted or idle-killed. Re-spawn resume-aware: start
        # ffmpeg at this segment's offset and number output from here so the
        # segments the fast path serves survive, writing the muxer index to a
        # side file so the canonical index.m3u8 is not clobbered.
        v = transcoder.variant_by_label(variant)
        if v is None:
            raise HTTPException(status_code=404, detail="unknown_variant")
        source = _contain(db, Path(mf.path))
        resume_offset_sec = t + seg_index * int(transcoder.HLS_SEG_DURATION)
        job = transcoder.manager.respawn_from_segment(
            user_id, mf.id, v, source,
            offset_bucket=t,
            start_number=seg_index,
            seek_offset_sec=resume_offset_sec,
            playlist_name="index.part.m3u8",
            opts=o,
            audio_only=is_audio_only(mf),
        )

    # Wait for the segment to be complete, not merely present: ffmpeg creates
    # seg N the moment it starts writing it, and serving that file early hands
    # the player a truncated segment (stall, then a retry storm). Complete =
    # the next segment exists, the playlist has ENDLIST, or ffmpeg has exited.
    seg_path = job.out_dir / segment
    deadline = time.time() + transcoder.START_WAIT_SEC
    while not segment_is_complete(job.out_dir, seg_index):
        if not job.is_running():
            if seg_path.exists():
                break
            raise HTTPException(status_code=404, detail="segment_not_produced")
        if time.time() > deadline:
            raise HTTPException(status_code=404, detail="segment_not_ready")
        time.sleep(0.2)
    job.touch()

    return serve_file_range(seg_path, range_header, content_type="video/mp2t")


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error"})
