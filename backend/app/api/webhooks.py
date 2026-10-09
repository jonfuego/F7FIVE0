"""Webhook receivers for Sonarr / Radarr / Lidarr.

Each incoming POST must present the shared secret in one of two ways:
  1. `X-Arr-Webhook-Token` header (preferred; used by Radarr + Sonarr Connect).
  2. HTTP Basic Auth password (Lidarr's Connect form exposes Username/Password
     but no custom headers, so we accept the secret there as a fallback).

On a relevant event we trigger a single-record refresh against the *arr API
so the local DB picks up the change within seconds of import.

Ignored events (Grab, Test, Health, Rename without file movement) return 204.
"""
from __future__ import annotations

import base64
import hmac
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.services import sync


log = logging.getLogger("f7five0.webhooks")
router = APIRouter()


# Events that should trigger a single-record refresh.
_RADARR_REFRESH_EVENTS = {
    "Download", "Upgrade", "Rename", "MovieFileDelete", "MovieAdded",
}
_SONARR_REFRESH_EVENTS = {
    "Download", "Upgrade", "Rename", "EpisodeFileDelete", "SeriesAdd",
}
_LIDARR_REFRESH_EVENTS = {
    "Download", "Upgrade", "Rename", "TrackFileDelete", "AlbumDownload", "ArtistAdded",
}


def _basic_auth_password(authorization: str | None) -> str | None:
    """Return the password from a `Authorization: Basic ...` header, or None."""
    if not authorization:
        return None
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    _, sep, pw = decoded.partition(":")
    if not sep:
        return None
    return pw


def verify_shared_secret(
    x_arr_webhook_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.arr_webhook_secret
    if not expected:
        raise HTTPException(status_code=503, detail="webhook_secret_not_configured")

    # Preferred path: custom header (Radarr, Sonarr).
    if x_arr_webhook_token and hmac.compare_digest(x_arr_webhook_token, expected):
        return

    # Fallback: HTTP Basic Auth password. Lidarr's Connect form has no custom
    # headers field, so it sends the shared secret as the Basic password.
    basic_pw = _basic_auth_password(authorization)
    if basic_pw and hmac.compare_digest(basic_pw, expected):
        return

    raise HTTPException(status_code=401, detail="invalid_webhook_token")


def _extract_id(payload: dict[str, Any], *keys: str) -> int | None:
    """Pull a numeric id out of nested webhook payloads."""
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    try:
        return int(cur)
    except (TypeError, ValueError):
        return None


@router.post("/radarr", dependencies=[Depends(verify_shared_secret)])
async def radarr_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    payload = await request.json()
    event = payload.get("eventType", "Unknown")
    log.info("radarr webhook event=%s", event)

    if event not in _RADARR_REFRESH_EVENTS:
        return {"received": True, "event": event, "refreshed": False}

    radarr_id = _extract_id(payload, "movie", "id")
    if radarr_id is None:
        log.warning("radarr webhook %s missing movie.id", event)
        return {"received": True, "event": event, "refreshed": False}

    stats = sync.SyncStats()
    try:
        movie = sync.refresh_movie(db, radarr_id, stats)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("refresh_movie failed for radarr_id=%s", radarr_id)
        raise HTTPException(status_code=500, detail="refresh_failed")
    sync.schedule_pending_enrichment(stats)

    return {
        "received": True,
        "event": event,
        "refreshed": True,
        "movie_id": str(movie.id) if movie else None,
    }


@router.post("/sonarr", dependencies=[Depends(verify_shared_secret)])
async def sonarr_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    payload = await request.json()
    event = payload.get("eventType", "Unknown")
    log.info("sonarr webhook event=%s", event)

    if event not in _SONARR_REFRESH_EVENTS:
        return {"received": True, "event": event, "refreshed": False}

    sonarr_id = _extract_id(payload, "series", "id")
    if sonarr_id is None:
        log.warning("sonarr webhook %s missing series.id", event)
        return {"received": True, "event": event, "refreshed": False}

    try:
        series = sync.refresh_series(db, sonarr_id)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("refresh_series failed for sonarr_id=%s", sonarr_id)
        raise HTTPException(status_code=500, detail="refresh_failed")

    return {
        "received": True,
        "event": event,
        "refreshed": True,
        "series_id": str(series.id) if series else None,
    }


@router.post("/lidarr", dependencies=[Depends(verify_shared_secret)])
async def lidarr_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    payload = await request.json()
    event = payload.get("eventType", "Unknown")
    log.info("lidarr webhook event=%s", event)

    if event not in _LIDARR_REFRESH_EVENTS:
        return {"received": True, "event": event, "refreshed": False}

    lidarr_id = _extract_id(payload, "artist", "id")
    if lidarr_id is None:
        log.warning("lidarr webhook %s missing artist.id", event)
        return {"received": True, "event": event, "refreshed": False}

    stats = sync.SyncStats()
    try:
        artist = sync.refresh_artist(db, lidarr_id, stats)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("refresh_artist failed for lidarr_id=%s", lidarr_id)
        raise HTTPException(status_code=500, detail="refresh_failed")
    sync.schedule_pending_enrichment(stats)

    return {
        "received": True,
        "event": event,
        "refreshed": True,
        "artist_id": str(artist.id) if artist else None,
    }
