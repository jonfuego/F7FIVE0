"""Media-file endpoints for track/audio + video selection and offline (Phase 2).

    GET /api/media-files/{id}/streams
        -> { subtitles: [...], audio: [...] }   (bearer auth)

    GET /api/media-files/{id}/subtitles/{stream_index}.vtt
        -> text/vtt, bearer OR signed query (?uid&exp&sig). 409 for image subs.

    GET /api/media-files/{id}/download?quality=...
        -> bearer OR signed query. Audio: original file. Video that can't
           direct-play: a server-side MP4 (H.264/AAC) download transcode.

IMPLEMENTATION HONESTY (read this before wiring the app side):
- `/streams` is fully implemented (ffprobe -show_streams, parsed to the
  contract shape).
- `/subtitles/{index}.vtt` is fully implemented for text subtitles (ffmpeg ->
  WebVTT) including signed-query auth; image subtitles return 409
  {reason: "image_subtitle_burn_required"}.
- `/download`:
    * Audio (or any already-direct-playable file) streams the ORIGINAL bytes
      with a Range-aware response. Fully implemented.
    * Video that cannot direct-play needs a server-side MP4 (H.264/AAC)
      transcode. The route, signing, quality validation, and the
      409 {reason: "not_available_offline"} path are fully wired. The actual
      transcode-to-MP4 invocation is STUBBED behind
      `transcoder.build_download_transcode_args` + a feature flag: until an
      operator opts in (settings.download_transcode_enabled), the route returns
      409 not_available_offline for non-direct-play video rather than spawning
      an unbounded ffmpeg job on the request path. See the transcoder service.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Optional

from fastapi import (
    APIRouter, Depends, Header, HTTPException, Query, Request, status,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_bearer_token, get_db
from app.config import settings
from app.models.media_file import MediaFile, ScanState
from app.models.user import User
from app.services import media_streams, path_map, playback
from app.services import security as security_service
from app.services.range_response import serve_file_range


router = APIRouter()


VALID_DOWNLOAD_QUALITIES = ("original", "1080p", "720p", "480p")


# ---------------------------------------------------------------------------
# Auth seam: bearer OR a valid signed query (subtitles + download only)
# ---------------------------------------------------------------------------
def optional_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Optional[User]:
    """Resolve the bearer user if present, else None (mirrors art.py).

    A present-but-invalid bearer still 401s. Missing header returns None so a
    signed-query request can proceed; the route decides whether None is OK.
    """
    if not authorization:
        return None
    token = get_bearer_token(authorization)
    return current_user(token=token, db=db)


def _require_ready_media_file(db: Session, media_file_id: uuid.UUID) -> MediaFile:
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="media_file_not_found")
    if mf.scan_state == ScanState.missing:
        raise HTTPException(status_code=410, detail="file_missing")
    if mf.scan_state != ScanState.ready:
        raise HTTPException(status_code=409, detail="file_not_ready")
    return mf


def _resolved_path(mf: MediaFile) -> str:
    return path_map.translate(mf.path) or mf.path


# ---------------------------------------------------------------------------
# GET /api/media-files/{id}/streams  (bearer auth)
# ---------------------------------------------------------------------------
@router.get("/media-files/{media_file_id}/streams")
def get_streams(
    media_file_id: uuid.UUID,
    request: Request,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    mf = _require_ready_media_file(db, media_file_id)
    result = media_streams.probe_streams(_resolved_path(mf))
    if result is None:
        raise HTTPException(status_code=409, detail="probe_failed")
    # Enrich each TEXT subtitle with a signed absolute vtt_url so a header-less
    # player (react-native-video text tracks) can load it without a bearer.
    # The public origin comes from the forwarded proto/host (the tunnel hands
    # us plain HTTP), so the app gets an https URL it is allowed to load.
    base = _public_base(request)
    for s in result.get("subtitles", []):
        if not media_streams.is_image_subtitle(s.get("codec")):
            try:
                s["vtt_url"] = security_service.build_signed_subtitle_url(
                    base, media_file_id, int(s["index"]), _user.id,
                )
            except (KeyError, ValueError, TypeError):
                pass
    return result


def content_disposition(filename: str) -> str:
    """`attachment` header that survives any file name.

    HTTP headers are latin-1, so a library name like "01 \u2212 Human.flac"
    (a Unicode minus) made the old f-string header raise UnicodeEncodeError and
    every download of that file 500'd. Send an ASCII fallback plus the RFC 5987
    `filename*` with the real UTF-8 name.
    """
    from urllib.parse import quote

    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _public_base(request: Request) -> str:
    """Absolute public origin for signed links (https behind the tunnel)."""
    from app.api.stream import _base_url

    return _base_url(request)


def _download_available(mf: MediaFile, quality: str) -> bool:
    """Whether /download can serve this file at `quality` (mirrors download())."""
    ok_direct, _reason = playback.can_direct_play(mf)
    if playback.is_audio_only(mf) or (ok_direct and quality == "original"):
        return True
    return bool(getattr(settings, "download_transcode_enabled", False))


# ---------------------------------------------------------------------------
# GET /api/media-files/{id}/download-url?quality=
#     Bearer-authenticated. Mints an absolute signed download URL so the
#     device's downloader (expo-file-system) fetches without a bearer that may
#     expire mid-download. 409 not_available_offline up front for video that
#     can't be offered, so the app can say so before queueing anything.
# ---------------------------------------------------------------------------
@router.get("/media-files/{media_file_id}/download-url")
def download_url(
    media_file_id: uuid.UUID,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    quality: str = Query("original"),
) -> dict:
    if quality not in VALID_DOWNLOAD_QUALITIES:
        raise HTTPException(status_code=422, detail="invalid_quality")
    mf = _require_ready_media_file(db, media_file_id)
    if not _download_available(mf, quality):
        raise HTTPException(status_code=409, detail={"reason": "not_available_offline"})
    return {
        "url": security_service.build_signed_download_url(
            _public_base(request), media_file_id, quality, user.id,
        ),
        "container": mf.container,
        "size_bytes": mf.size_bytes,
        "kind": mf.kind.value,
    }


# ---------------------------------------------------------------------------
# GET /api/media-files/{id}/subtitles/{stream_index}.vtt
#     bearer OR signed query. text/vtt. 409 for image subs.
# ---------------------------------------------------------------------------
@router.get("/media-files/{media_file_id}/subtitles/{stream_index}.vtt")
def get_subtitle_vtt(
    media_file_id: uuid.UUID,
    stream_index: int,
    user: Annotated[Optional[User], Depends(optional_current_user)],
    db: Annotated[Session, Depends(get_db)],
    uid: Optional[str] = None,
    exp: Optional[int] = None,
    sig: Optional[str] = None,
) -> PlainTextResponse:
    """Extract subtitle stream `stream_index` to WebVTT.

    Auth: a bearer token OR a valid signed query bound to this exact
    (media_file_id, stream_index). A present-but-bad/expired signature with no
    bearer is a hard 401. Image-based subtitle codecs 409 with
    {reason: image_subtitle_burn_required}.
    """
    if user is None:
        if not (
            uid is not None and exp is not None and sig is not None
            and security_service.verify_media_url_params(
                media_file_id, "subtitle", str(stream_index), uid, exp, sig,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="subtitle_auth_required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    mf = _require_ready_media_file(db, media_file_id)
    path = _resolved_path(mf)

    # Identify the target stream so we can reject image subs before spending an
    # ffmpeg extract pass on something that can't become text.
    streams = media_streams.probe_streams(path)
    if streams is None:
        raise HTTPException(status_code=409, detail="probe_failed")
    target = next(
        (s for s in streams["subtitles"] if s.get("index") == stream_index),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="subtitle_stream_not_found")
    if media_streams.is_image_subtitle(target.get("codec")):
        raise HTTPException(
            status_code=409,
            detail={"reason": "image_subtitle_burn_required"},
        )

    vtt = media_streams.extract_subtitle_vtt(path, stream_index)
    if vtt is None:
        raise HTTPException(status_code=409, detail="subtitle_extract_failed")
    return PlainTextResponse(
        content=vtt,
        media_type="text/vtt",
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ---------------------------------------------------------------------------
# GET /api/media-files/{id}/download?quality=...
#     bearer OR signed query.
# ---------------------------------------------------------------------------
@router.get("/media-files/{media_file_id}/download")
def download(
    media_file_id: uuid.UUID,
    request: Request,
    user: Annotated[Optional[User], Depends(optional_current_user)],
    db: Annotated[Session, Depends(get_db)],
    quality: str = Query("original"),
    uid: Optional[str] = None,
    exp: Optional[int] = None,
    sig: Optional[str] = None,
) -> object:
    """Serve a file for offline download.

    Audio (or any direct-playable file): the ORIGINAL bytes, Range-aware. Video
    that cannot direct-play: a server-side MP4 (H.264/AAC) download transcode
    when `settings.download_transcode_enabled` is on; otherwise 409
    {reason: not_available_offline}. The chosen `quality` is bound into the
    signature so a signed link can't be retargeted to a different rendition.
    """
    if quality not in VALID_DOWNLOAD_QUALITIES:
        raise HTTPException(status_code=422, detail="invalid_quality")

    if user is None:
        if not (
            uid is not None and exp is not None and sig is not None
            and security_service.verify_media_url_params(
                media_file_id, "download", quality, uid, exp, sig,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="download_auth_required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    mf = _require_ready_media_file(db, media_file_id)
    path = Path(_resolved_path(mf))

    ok_direct, _reason = playback.can_direct_play(mf)
    is_audio = playback.is_audio_only(mf)

    # Audio always downloads the original. Video that can direct-play (already
    # H.264/AAC in an MP4-family container) also downloads the original at
    # `original` quality; a lower quality request for such a file still needs a
    # transcode.
    if is_audio or (ok_direct and quality == "original"):
        range_header = request.headers.get("range")
        headers = {"Content-Disposition": content_disposition(path.name)}
        resp = serve_file_range(path, range_header)
        resp.headers.update(headers)
        return resp

    # Non-direct-play video (or a quality downscale request): needs an MP4
    # H.264/AAC download transcode. Wired but gated behind an opt-in flag; the
    # actual transcode is stubbed in the transcoder service. Until enabled, this
    # is the documented 409 path.
    if not getattr(settings, "download_transcode_enabled", False):
        raise HTTPException(
            status_code=409,
            detail={"reason": "not_available_offline"},
        )

    # Opt-in path: build the MP4 transcode and serve it. Stubbed invocation.
    from app.services import transcoder

    try:
        mp4_path = transcoder.build_download_mp4(mf, quality)
    except NotImplementedError:
        raise HTTPException(
            status_code=409,
            detail={"reason": "not_available_offline"},
        )
    range_header = request.headers.get("range")
    resp = serve_file_range(Path(mp4_path), range_header, content_type="video/mp4")
    resp.headers["Content-Disposition"] = content_disposition(Path(mp4_path).name)
    return resp


# ---------------------------------------------------------------------------
# GET /api/media-files/{media_file_id}/next-episode
#     The episode that follows this one (Plex "Up Next"). The native player
#     shows a credits countdown and then plays it. null when the file is not
#     an episode, is the last episode, or the next one has no ready file.
# ---------------------------------------------------------------------------
@router.get("/media-files/{media_file_id}/next-episode")
def next_episode_for(
    media_file_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Optional[dict]:
    from sqlalchemy import select

    from app.models.media_file import MediaKind
    from app.models.tv import Episode

    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="media_file_not_found")
    if mf.kind != MediaKind.episode:
        return None
    ep = db.get(Episode, mf.ref_id)
    if ep is None:
        return None
    siblings = sorted(
        db.scalars(select(Episode).where(Episode.series_id == ep.series_id)),
        key=lambda e: (e.season_number, e.episode_number),
    )
    # Specials (season 0) only chain into each other, never into season 1.
    if ep.season_number > 0:
        siblings = [e for e in siblings if e.season_number > 0]
    after = [e for e in siblings
             if (e.season_number, e.episode_number) > (ep.season_number, ep.episode_number)]
    for nxt in after:
        nf = db.scalars(
            select(MediaFile).where(
                MediaFile.kind == MediaKind.episode,
                MediaFile.ref_id == nxt.id,
                MediaFile.scan_state == ScanState.ready,
            )
        ).first()
        if nf is None:
            continue
        label = f"S{nxt.season_number:02d}E{nxt.episode_number:02d}"
        return {
            "series_id": str(ep.series_id),
            "episode_id": str(nxt.id),
            "media_file_id": str(nf.id),
            "season_number": nxt.season_number,
            "episode_number": nxt.episode_number,
            "title": f"{label} - {nxt.title}" if nxt.title else label,
        }
    return None
