"""First-run setup: create the first admin from the browser.

A silent install (winget, `Setup.exe /SILENT`) has nobody to type an admin
password, so install.ps1 finishes without an account and the web app asks for
one on the first visit instead, the way Jellyfin and Plex do.

Two rules keep this from being a takeover hole:

- It works only while the server has no account at all (the seeded system user
  does not count). The first admin closes it for good, and two requests that
  race are serialized (PostgreSQL advisory lock), so only one wins.
- It answers only a browser on the server PC itself. `request.state.client_ip`
  is the real client (SEC-P1-1: the Next proxy stamps a LAN browser's address,
  and a tunnel's CF-Connecting-IP / X-Forwarded-For pass through), so a phone on
  the LAN or anyone through a tunnel gets 403 `setup_local_only` and is told to
  finish on the server PC. Setup's last page opens http://localhost there.

These routes are not BFF paths, so the browser reaches them through the Next
proxy (`proxy.ts` forwards non-BFF `/api/*` to the API with the peer-stamped
headers). The page signs in through the normal BFF login afterwards.
"""
from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import USERNAME_PATTERN
from app.models.user import User, UserRole
from app.services import auth_events
from app.services.security import hash_password

router = APIRouter()

# Any fixed number; it only has to differ from the per-username login locks,
# which are hashes of a name (login_throttle.lock_key).
_SETUP_LOCK_KEY = 7_550_001


class SetupState(BaseModel):
    needs_admin: bool
    # Whether this browser may create the admin (it is on the server PC).
    local: bool


class FirstAdminRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("username", mode="before")
    @classmethod
    def _lower(cls, v: object) -> object:
        # People type "Jon"; usernames are stored lowercase like everywhere else.
        return v.strip().lower() if isinstance(v, str) else v


def _needs_admin(db: Session) -> bool:
    count = db.scalar(
        select(func.count()).select_from(User).where(User.role != UserRole.system)
    )
    return int(count or 0) == 0


def _is_local(request: Request) -> bool:
    ip = getattr(request.state, "client_ip", None) or ""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


@router.get("/state", response_model=SetupState)
def setup_state(request: Request, db: Annotated[Session, Depends(get_db)]) -> SetupState:
    return SetupState(needs_admin=_needs_admin(db), local=_is_local(request))


@router.post("/admin", status_code=201)
def create_first_admin(
    body: FirstAdminRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    # Same answer for a remote caller whether or not setup is done: nothing
    # about this server's accounts is revealed off the PC.
    if not _is_local(request):
        raise HTTPException(status_code=403, detail="setup_local_only")

    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SETUP_LOCK_KEY})
    if not _needs_admin(db):
        db.rollback()
        raise HTTPException(status_code=409, detail="setup_done")

    username = body.username.lower()
    name = (body.display_name or "").strip() or username
    user = User(
        username=username,
        display_name=name,
        password_hash=hash_password(body.password),
        role=UserRole.admin,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    auth_events.record_auth_event(
        db, user_id=user.id, event="first_admin_created", request=request,
    )
    db.commit()
    return {"username": username}
