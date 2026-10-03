"""Admin > Remote access endpoints (admin only).

GET    /api/admin/remote-access         current setup + last run
POST   /api/admin/remote-access         start a run {method, host?, duckdns_token?, tunnel_token?}
GET    /api/admin/remote-access/run     live run state (poll while a run is active)
POST   /api/admin/remote-access/cancel  ask the helper to stop
DELETE /api/admin/remote-access         turn remote access off (a run with method "off")

The work happens in the F7FIVE0-RemoteAccess scheduled task; see
app/services/remote_access.py for the protocol.
"""
from __future__ import annotations

import threading
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_admin
from app.config import settings
from app.models.user import User
from app.services import remote_access as ra

router = APIRouter()
_start_lock = threading.Lock()


class RemoteAccessRequest(BaseModel):
    method: str
    host: Optional[str] = None
    duckdns_token: Optional[str] = None
    tunnel_token: Optional[str] = None


class RunOut(BaseModel):
    id: Optional[str] = None
    method: Optional[str] = None
    host: Optional[str] = None
    state: str
    step: Optional[str] = None
    sign_in_url: Optional[str] = None
    sign_in_deadline: Optional[str] = None
    sign_in_seconds_left: Optional[int] = None
    public_url: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    log: list[str] = []


class RemoteAccessOut(BaseModel):
    available: bool
    method: Optional[str] = None
    public_url: Optional[str] = None
    # Address saved by the last successful run when the API has not picked
    # it up yet (restart pending).
    pending_public_url: Optional[str] = None
    reachable: Optional[bool] = None
    tunnel_service: Optional[str] = None
    proxy_service: Optional[str] = None
    web_port: int
    run: RunOut


def get_helper() -> ra.Helper:
    return ra.get_helper()


@router.get("", response_model=RemoteAccessOut)
def remote_access_status(
    _admin: Annotated[User, Depends(require_admin)],
    helper: Annotated[ra.Helper, Depends(get_helper)],
    probe: bool = True,
) -> RemoteAccessOut:
    p = ra.paths()
    current = ra.read_json(p.current)
    public_url = settings.public_url.strip().rstrip("/")
    tunnel = ra.service_state("F7FIVE0-Tunnel")
    proxy = ra.service_state("F7FIVE0-Proxy")
    saved = (current or {}).get("public_url") or None
    pending = saved if saved and saved.rstrip("/") != public_url else None
    return RemoteAccessOut(
        available=helper.available(),
        method=ra.infer_method(public_url, current, tunnel, proxy),
        public_url=public_url or None,
        pending_public_url=pending,
        reachable=ra.probe(public_url) if probe else None,
        tunnel_service=tunnel,
        proxy_service=proxy,
        web_port=settings.web_port,
        run=RunOut(**ra.run_state()),
    )


def _start(helper: ra.Helper, req: dict, admin: User) -> RunOut:
    if not helper.available():
        raise HTTPException(status_code=503, detail="helper_unavailable")
    with _start_lock:
        try:
            state = ra.start_run(helper, req, requested_by=admin.username)
        except ra.RequestError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except ra.HelperError as exc:
            raise HTTPException(status_code=503, detail="helper_failed") from exc
    return RunOut(**state)


@router.post("", response_model=RunOut, status_code=202)
def start_remote_access(
    body: RemoteAccessRequest,
    admin: Annotated[User, Depends(require_admin)],
    helper: Annotated[ra.Helper, Depends(get_helper)],
) -> RunOut:
    if (body.method or "").strip().lower() == "off":
        raise HTTPException(status_code=400, detail="unknown_method")
    try:
        req = ra.validate(body.method, body.host or "", body.duckdns_token or "", body.tunnel_token or "")
    except ra.RequestError as exc:
        raise HTTPException(status_code=400, detail=exc.code) from exc
    return _start(helper, req, admin)


@router.delete("", response_model=RunOut, status_code=202)
def turn_off_remote_access(
    admin: Annotated[User, Depends(require_admin)],
    helper: Annotated[ra.Helper, Depends(get_helper)],
) -> RunOut:
    return _start(helper, ra.validate("off"), admin)


@router.get("/run", response_model=RunOut)
def remote_access_run(_admin: Annotated[User, Depends(require_admin)]) -> RunOut:
    return RunOut(**ra.run_state())


@router.post("/cancel", response_model=RunOut, status_code=202)
def cancel_remote_access(_admin: Annotated[User, Depends(require_admin)]) -> RunOut:
    return RunOut(**ra.cancel_run())
