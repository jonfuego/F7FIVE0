"""Self-service device-session management (F7FIVE0 2.0 native).

A signed-in user can list their own sessions and revoke one or all-but-current.
This is what makes long-lived native sessions safe: a lost phone or TV can be
signed out from any other device. Admin revocation of *any* user's session
stays in the admin router; these endpoints only ever touch the caller's own
rows and never expose token material.

Route prefix note: mounted at `/api/sessions`, which is NOT under `/api/admin/`
(the only `/api` prefix the tunnel documents as routed to Next on :3001), so it
resolves to the API on :8001 under the documented ingress. See the smoke file's
route table and reports/BLOCKERS.md B2.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_session_id, current_user, evict_session_cache, get_db
from app.api.schemas import SessionOut, SessionRevokeResult
from app.models.user import Session as UserSession, User


router = APIRouter()


def _active_sessions(db: Session, user_id: uuid.UUID) -> list[UserSession]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.last_seen_at.desc().nullslast(),
                  UserSession.created_at.desc())
    )
    return list(rows)


@router.get("", response_model=list[SessionOut])
def list_my_sessions(
    user: Annotated[User, Depends(current_user)],
    sid: Annotated[uuid.UUID, Depends(current_session_id)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SessionOut]:
    """List the caller's active sessions, flagging the current one."""
    out: list[SessionOut] = []
    for s in _active_sessions(db, user.id):
        model = SessionOut.model_validate(s)
        model.current = s.id == sid
        out.append(model)
    return out


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Revoke one of the caller's own sessions. 404 if it isn't theirs, so a
    user can't probe another user's session ids."""
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    # Evict the revocation micro-cache so the kill takes effect immediately
    # rather than waiting out the 10s TTL. Cheap; see deps._session_cache.
    evict_session_cache(session_id)


@router.delete("", response_model=SessionRevokeResult)
def revoke_my_other_sessions(
    user: Annotated[User, Depends(current_user)],
    sid: Annotated[uuid.UUID, Depends(current_session_id)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionRevokeResult:
    """Revoke all of the caller's sessions except the one in use."""
    now = datetime.now(timezone.utc)
    victims = [s for s in _active_sessions(db, user.id) if s.id != sid]
    for s in victims:
        s.revoked_at = now
    db.commit()
    for s in victims:
        evict_session_cache(s.id)
    return SessionRevokeResult(revoked=len(victims))
