"""Client-support endpoints for the native app (F7FIVE0 2.0).

- GET  /api/client/min-version : no auth. Minimum supported app version per
  platform, so an out-of-date build shows an "update required" screen instead
  of failing unpredictably. This is the controlled replacement for the old
  service-worker stale-bundle problem.
- GET  /api/client/features : no auth. Optional integrations (Requests,
  passkeys) and the public address.
- GET  /api/client/assetlinks.json : no auth. Digital Asset Links for the
  Android app(s), served by the web server at /.well-known/assetlinks.json.
- POST /api/client/errors : auth required. Phase 4 crash reporting with no
  third-party service. Writes one structured line to the API log; the payload
  is hard-capped at 8 KB.

Route prefix note: mounted at `/api/client`, NOT under `/api/admin/`, so it
resolves to the API on :8001 under the documented tunnel ingress. See the smoke
file's route table and reports/BLOCKERS.md B2.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import current_user
from app.api.schemas import ClientErrorReport, MinClientVersionOut
from app.config import settings
from app.models.user import User


router = APIRouter()
log = logging.getLogger("f7five0.client")

# Hard cap on the crash-report body. Generous for a message + stack, small
# enough that a misbehaving or hostile client can't flood the API log.
_MAX_ERROR_BYTES = 8 * 1024


@router.get("/min-version", response_model=MinClientVersionOut)
def min_version() -> MinClientVersionOut:
    """No auth: the app calls this on launch before it has a token."""
    return MinClientVersionOut(
        android=settings.min_client_version_android,
        ios=settings.min_client_version_ios,
        android_tv=settings.min_client_version_android_tv,
        tvos=settings.min_client_version_tvos,
    )


@router.get("/features")
def features() -> dict:
    """No auth: which optional integrations this server has turned on, so
    the web app and native app can hide what does not apply (for example the
    Requests screens on a server without Radarr / Sonarr)."""
    from app.api.requests import requests_enabled
    from app.models.request import KIND_MOVIE, KIND_SERIES

    movie = requests_enabled(KIND_MOVIE)
    series = requests_enabled(KIND_SERIES)
    return {
        "requests": {"enabled": movie or series, "movie": movie, "series": series},
        "public_url": settings.public_url.rstrip("/") or None,
        "passkeys": {
            "enabled": settings.passkeys_enabled,
            "rp_id": settings.webauthn_rp_id_effective or None,
        },
        # Hardware (NVENC) transcoding. Without it the web player starts
        # transcoded video at 720p instead of the top of the ladder.
        "transcode": {"hardware": bool(settings.nvenc_enabled)},
    }


@router.get("/assetlinks.json")
def assetlinks() -> list[dict]:
    """No auth: Digital Asset Links statements for the Android apps allowed to
    use this server's passkeys and links. The web server serves this at
    /.well-known/assetlinks.json (see frontend/middleware.ts). Empty list when
    passkeys are off or no app certificate is configured."""
    if not settings.passkeys_enabled:
        return []
    return [
        {
            "relation": [
                "delegate_permission/common.handle_all_urls",
                "delegate_permission/common.get_login_creds",
            ],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": certs,
            },
        }
        for package, certs in settings.webauthn_android_apps
    ]


@router.post("/errors", status_code=status.HTTP_204_NO_CONTENT)
async def report_error(
    request: Request,
    user: Annotated[User, Depends(current_user)],
) -> None:
    """Accept one client crash/error report and log it as a single line.

    The raw body is size-checked before parsing so an oversized payload is
    rejected with 413 without ever being buffered into a model.
    """
    raw = await request.body()
    if len(raw) > _MAX_ERROR_BYTES:
        raise HTTPException(status_code=413, detail="payload_too_large")
    try:
        report = ClientErrorReport.model_validate_json(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_error_report")

    # One structured line. json.dumps keeps it grep-able and safe against
    # newlines in user-supplied fields (they get escaped, so the log line
    # can't be split or forged).
    payload = {
        "user_id": str(user.id),
        "platform": report.platform,
        "client_version": report.client_version,
        "fatal": report.fatal,
        "context": report.context,
        "message": report.message,
        "stack": report.stack,
    }
    line = json.dumps(payload, ensure_ascii=False, default=str)
    if report.fatal:
        log.error("client_error %s", line)
    else:
        log.warning("client_error %s", line)
