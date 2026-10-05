"""Stream control endpoints on the API app.

These run on `F7FIVE0-API` (port 8001, path-prefixed `/api`). They issue
signed URLs that the `F7FIVE0-Stream` gateway (port 8002, path-prefixed
`/stream`) validates and serves bytes for. No bytes flow through these
handlers; they are thin decision endpoints.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import uuid
from typing import Annotated, Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.api.schemas import StreamStartRequest, StreamStartResponse
from app.config import settings
from app.models.art import ENTITY_ALBUM, ENTITY_MOVIE, ENTITY_SERIES, ROLE_COVER, ROLE_POSTER
from app.models.media_file import MediaFile, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, MusicVideo, Track
from app.models.tv import Episode
from app.models.user import User
from app.services import media_streams, playback
from app.services.art import resolve_art
from app.services.security import build_signed_art_url, sign_stream_url_params
from app.services.track_opts import resolve_track_opts


log = logging.getLogger("f7five0.api.stream")

# `/api/art/{kind}/{uuid}/{role}` (with an optional ?v= cache-buster), the
# shape services/art.resolve_art hands out as cover_path.
_ART_PATH_RE = re.compile(
    r"^/api/art/(?P<kind>[a-z_]+)/(?P<id>[0-9a-fA-F-]{36})/(?P<role>[a-z_]+)(?:\?.*)?$"
)


def _local_art_path(db: Session, mf: MediaFile) -> Optional[str]:
    """The local `/api/art/...` path for this file's artwork: album cover for a
    track, poster for a movie, series poster for an episode. None otherwise or
    on any lookup failure."""
    try:
        kind = mf.kind.value
        if kind == "track":
            t = db.get(Track, mf.ref_id)
            if t is not None:
                return resolve_art(db, entity_kind=ENTITY_ALBUM, entity_id=t.album_id, role=ROLE_COVER)
        elif kind == "movie":
            return resolve_art(db, entity_kind=ENTITY_MOVIE, entity_id=mf.ref_id, role=ROLE_POSTER)
        elif kind == "episode":
            ep = db.get(Episode, mf.ref_id)
            if ep is not None:
                return resolve_art(db, entity_kind=ENTITY_SERIES, entity_id=ep.series_id, role=ROLE_POSTER)
    except Exception:
        log.exception("art lookup failed for media file %s", mf.id)
    return None


def _signed_art_url(request: Request, user_id: uuid.UUID,
                    cover_path: Optional[str]) -> Optional[str]:
    """Absolute, HMAC-signed art URL for a header-less loader (the Android
    media notification / lock screen). None when there is no local art path.
    Never raises: artwork is cosmetic and must not fail a stream start."""
    if not cover_path:
        return None
    m = _ART_PATH_RE.match(cover_path)
    if not m:
        return None
    try:
        return build_signed_art_url(
            _base_url(request), m.group("kind"), uuid.UUID(m.group("id")),
            m.group("role"), user_id,
        )
    except Exception:
        log.exception("could not sign art url for %s", cover_path)
        return None


router = APIRouter()


# HLS resume offsets are quantized to this many seconds so one movie
# resumed at second 45:12 vs 45:13 vs 45:14 doesn't spawn three separate
# ffmpeg processes with three separate cache directories. 10s matches
# the `hls_time=6` segment cadence with a little headroom. The client
# passes raw seconds; the server buckets before signing + spawning.
OFFSET_BUCKET_SEC = 10


def _quantize_offset(resume_sec: Optional[int]) -> int:
    if resume_sec is None or resume_sec <= 0:
        return 0
    return (resume_sec // OFFSET_BUCKET_SEC) * OFFSET_BUCKET_SEC


def _base_url(request: Request) -> str:
    """Absolute base URL for gateway links, e.g. https://media.example.com.

    Prefers `X-Forwarded-Host` / `X-Forwarded-Proto` (set by the web
    server's proxy layer and by Cloudflare Tunnel) so links match the origin
    the client actually used, whether that is https://media.example.com or
    http://192.168.1.20:3001 on a LAN. Falls back to `Host` and the request
    scheme when nothing is forwarded (local dev).
    """
    def _first(name: str) -> str:
        return (request.headers.get(name) or "").split(",")[0].strip()

    host = _first("x-forwarded-host") or _first("host") or f"127.0.0.1:{settings.stream_port}"
    proto = _first("x-forwarded-proto") or request.url.scheme or "http"
    # Some front doors (Tailscale Funnel among them) terminate HTTPS without
    # saying so. When the request arrived on the configured public address,
    # trust its scheme so players never get http:// links on an https page.
    public = urlsplit(settings.public_url or "")
    if public.scheme and public.netloc and public.netloc.lower() == host.lower():
        proto = public.scheme
    return f"{proto}://{host}"


def _title_for(db: Session, mf: MediaFile) -> Optional[str]:
    """Best-effort human title for the playback card. Never raises."""
    try:
        if mf.kind.value == "movie":
            m = db.get(Movie, mf.ref_id)
            if m is not None:
                return f"{m.title}" + (f" ({m.year})" if m.year else "")
        elif mf.kind.value == "episode":
            ep = db.get(Episode, mf.ref_id)
            if ep is not None:
                label = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
                return f"{label} - {ep.title}" if ep.title else label
        elif mf.kind.value == "track":
            t = db.get(Track, mf.ref_id)
            if t is not None:
                return t.title
        elif mf.kind.value == "music_video":
            mv = db.get(MusicVideo, mf.ref_id)
            if mv is not None:
                artist = db.get(Artist, mv.artist_id)
                parts = [artist.name] if artist is not None else []
                parts.append(mv.title)
                label = " - ".join(parts)
                return f"{label} ({mv.year})" if mv.year else label
    except Exception:
        return None
    return None


def _audio_artwork_for(db: Session, mf: MediaFile) -> tuple[
    Optional[str], Optional[str], Optional[str]
]:
    """Resolve (cover_path, artist_name, album_title) for a track MediaFile.

    Returns (None, None, None) for non-audio kinds or when any lookup fails.
    The join chain is track -> album -> artist; all three are cached in
    session-local state so the two extra DB fetches vs. `_title_for` land
    on identity-map hits after the first call.
    """
    if mf.kind.value != "track":
        return None, None, None
    try:
        t = db.get(Track, mf.ref_id)
        if t is None:
            return None, None, None
        album = db.get(Album, t.album_id)
        if album is None:
            return None, None, None
        artist = db.get(Artist, album.artist_id)
        return album.cover_path, (artist.name if artist else None), album.title
    except Exception:
        return None, None, None


@router.post("/stream/start", response_model=StreamStartResponse)
def stream_start(
    body: StreamStartRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamStartResponse:
    mf = db.get(MediaFile, body.file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="file_not_found")
    if mf.scan_state == ScanState.missing:
        raise HTTPException(status_code=410, detail="file_missing")
    if mf.scan_state == ScanState.error:
        raise HTTPException(status_code=409, detail="file_unplayable")
    if mf.scan_state != ScanState.ready:
        raise HTTPException(status_code=409, detail="file_not_ready")

    # Cast loads are logged so the passkey/cast smoke check can count them by
    # media kind (track -> music, everything else -> video). The literal
    # "stream_start purpose=cast" is what the smoke script greps for in the API
    # log. No behavior change beyond the log line.
    if body.purpose == "cast":
        log.info(
            "stream_start purpose=cast kind=%s media_file_id=%s",
            mf.kind.value, mf.id,
        )

    decision = playback.decide(mf)
    mode = decision.mode

    # Track selection (spec section I). Only video can carry a pick: an
    # alternate audio track or a burned image subtitle forces an HLS remux
    # with that stream mapped, and a quality ceiling below the source caps
    # the HLS ladder. The choices become a signed `o` token that keys the
    # transcode session and its cache dir. Text subtitles never force a
    # transcode; the client side-loads them as signed WebVTT.
    opts_token = ""
    wants_tracks = (
        body.audio_track_index is not None
        or (body.subtitle is not None and body.subtitle != "off")
        or (body.quality not in (None, "original"))
    )
    if wants_tracks and not playback.is_audio_only(mf):
        needs_probe = body.audio_track_index is not None or (
            body.subtitle is not None and body.subtitle != "off"
        )
        streams = media_streams.probe_streams(mf.path) if needs_probe else None
        opts = resolve_track_opts(
            audio_track_index=body.audio_track_index,
            subtitle=body.subtitle,
            quality=body.quality,
            source_height=mf.height,
            streams=streams,
            keep_source_height=not settings.nvenc_enabled,
        )
        opts_token = opts.to_token()
        if opts_token:
            mode = "hls"

    # Direct-play ignores the offset (the client handles seeking via Range
    # requests against the MP4), so it always signs bucket=0 regardless of
    # what the caller passed. HLS carries the caller's bucket through to
    # the transcoder via the `t` query param.
    bucket = _quantize_offset(body.resume_sec) if mode == "hls" else 0
    # Exact-second landing. The encode starts at the bucket, so the HLS
    # timeline's second 0 is `bucket` seconds into the source. The caller asked
    # to resume at `resume_sec` (the true source position). To land on that
    # exact second the client seeks `requested - bucket` seconds INTO the
    # stream after it loads, instead of sitting at the bucket boundary (up to
    # OFFSET_BUCKET_SEC-1 seconds early). For direct play nothing is bucketed,
    # so the true position is 0 and there is nothing to seek within.
    requested_sec = (
        max(0, body.resume_sec) if (mode == "hls" and body.resume_sec) else 0
    )
    seek_within = requested_sec - bucket  # 0..OFFSET_BUCKET_SEC-1 for HLS
    params = sign_stream_url_params(user.id, mf.id, offset_bucket=bucket,
                                    opts=opts_token)
    q = {
        "uid": params["uid"],
        "exp": params["exp"],
        "sig": params["sig"],
        "t": params["t"],
    }
    if opts_token:
        q["o"] = opts_token
    query = urlencode(q)

    if mode == "direct":
        path = f"/stream/direct/{mf.id}"
    else:
        path = f"/stream/hls/{mf.id}/master.m3u8"

    url = f"{_base_url(request)}{path}?{query}"
    exp_dt = datetime.fromtimestamp(int(params["exp"]), tz=timezone.utc)

    cover_path, artist_name, album_title = _audio_artwork_for(db, mf)

    return StreamStartResponse(
        media_file_id=mf.id,
        mode=mode,
        variant=decision.variant if mode == decision.mode else None,
        url=url,
        expires_at=exp_dt,
        title=_title_for(db, mf),
        duration_sec=mf.duration_sec,
        container=mf.container,
        video_codec=mf.video_codec,
        audio_codec=mf.audio_codec,
        width=mf.width,
        height=mf.height,
        cover_path=cover_path,
        art_url=_signed_art_url(request, user.id, _local_art_path(db, mf)),
        artist_name=artist_name,
        album_title=album_title,
        # Echo the Phase 2 track-selection choices back. `quality` defaults to
        # "original" when omitted so the client always has a concrete value;
        # audio/subtitle stay null when not requested. The effective choice is
        # carried by the signed `o` token (see `track_opts` in the response).
        audio_track_index=body.audio_track_index,
        subtitle=body.subtitle,
        quality=body.quality or "original",
        track_opts=opts_token or None,
        # True source position the caller resumed at (not the bucket). The
        # client adds this to the element clock to report the real position.
        offset_sec=requested_sec,
        # Where the HLS encode actually begins (element clock 0 == this second).
        timeline_offset_sec=bucket,
        # How far to seek into the stream after start to hit the exact second.
        seek_within_sec=seek_within,
    )
