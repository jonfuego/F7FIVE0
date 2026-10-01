"""FastAPI dependencies: DB session, current user, admin guard."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import Session as UserSession, User, UserRole
from app.services.security import decode_access_token


# Grace window after a session's revoked_at before its access tokens stop
# working. Normal refresh rotation revokes the old session the instant it
# issues the new one; an access token already in flight (or the refresh
# request itself) would otherwise 401 in that race. 120s is comfortably
# longer than any single request and far shorter than the 15-minute access
# TTL, so a genuinely revoked token still dies fast.
_REVOCATION_GRACE = timedelta(seconds=120)

# In-process micro-cache for the session-revocation lookup. A library grid
# load fans out one authenticated request per poster; without this, every one
# runs its own `db.get(UserSession, ...)`, which is the query the
# security-hardening pass added and which tipped the connection pool over. The
# cache collapses a poster burst down to one session read per session.
#
# The TTL is the entire safety argument and MUST NOT be raised. The revocation
# check exists so a revoked token dies inside its 15-minute TTL rather than
# living the whole window. A 10-second cache means a revoked session survives
# at most 10 seconds beyond the existing 120-second grace. That is acceptable;
# 60 seconds or 5 minutes is not, because it starts approaching the TTL the
# check was meant to shorten. A longer TTL needs a deliberate security
# decision, not a drive-by change here.
#
# Entries are (revoked_at, expires_at, user_id, cached_at). Sync dependencies
# run across threadpool threads; dict get/set are atomic under the GIL, and the
# worst case of a race is a redundant DB read or a <=10s-stale entry.
_SESSION_CACHE_TTL = timedelta(seconds=10)
_session_cache: dict[
    uuid.UUID,
    tuple[Optional[datetime], datetime, uuid.UUID, datetime],
] = {}


def evict_session_cache(session_id: uuid.UUID) -> None:
    """Drop a session's cached revocation state.

    Called from the admin revoke path so a manual revoke takes effect
    immediately instead of waiting out the TTL. The 10-second TTL bounds the
    damage even if this is never called.
    """
    _session_cache.pop(session_id, None)


def get_bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_bearer_token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1].strip()


def current_user(
    token: Annotated[str, Depends(get_bearer_token)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid_token",
                            headers={"WWW-Authenticate": "Bearer"})

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="invalid_token")

    # Bind the token to its session row. Password change, admin disable, and
    # refresh-reuse detection all revoke sessions; without this check an
    # already-issued access token stays valid up to its 15-minute TTL. One
    # indexed lookup on the PK closes that gap.
    try:
        session_id = uuid.UUID(payload["sid"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="invalid_token")

    now = datetime.now(timezone.utc)
    cached = _session_cache.get(session_id)
    if cached is not None and now - cached[3] < _SESSION_CACHE_TTL:
        revoked_at, expires_at, sess_user_id, _ = cached
    else:
        session = db.get(UserSession, session_id)
        if session is None or session.user_id != user_id:
            _session_cache.pop(session_id, None)
            raise HTTPException(status_code=401, detail="session_revoked")
        revoked_at = session.revoked_at
        expires_at = session.expires_at
        sess_user_id = session.user_id
        _session_cache[session_id] = (revoked_at, expires_at, sess_user_id, now)

    if sess_user_id != user_id:
        raise HTTPException(status_code=401, detail="session_revoked")
    if revoked_at is not None and now > revoked_at + _REVOCATION_GRACE:
        raise HTTPException(status_code=401, detail="session_revoked")
    if expires_at <= now:
        raise HTTPException(status_code=401, detail="session_expired")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="inactive_or_unknown_user")
    return user


def current_session_id(
    token: Annotated[str, Depends(get_bearer_token)],
) -> uuid.UUID:
    """The session id (`sid`) the caller's access token was issued for.

    Used by the self-service session endpoints to flag the caller's own
    session as current and to refuse revoking the one in use from the
    revoke-one path. Decoding is cheap and already validated the same way
    `current_user` validates it; a request that reaches here has passed
    `current_user` too, so we only translate errors to 401.
    """
    try:
        payload = decode_access_token(token)
        return uuid.UUID(payload["sid"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="invalid_token",
                            headers={"WWW-Authenticate": "Bearer"})


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin_required")
    return user
