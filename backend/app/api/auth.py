"""Auth endpoints: login, refresh, logout, and admin user management.

Token model:
  - access_token: short-lived JWT (15 min default), bearer header.
  - refresh_token: opaque random, 30 days, rotated on every refresh.
    Server stores SHA-256 hash in `sessions.refresh_token_hash`. The previous
    row is revoked when a new one is issued so reuse is detectable.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, require_admin
from app.services import login_throttle
from app.api.schemas import (
    LoginRequest, LogoutRequest, PasswordChangeRequest, PasswordResetRequest,
    ProfileUpdateRequest, RefreshRequest, TokenPair, UserCreateRequest, UserOut,
    UserUpdateRequest,
)
from app.config import settings
from app.models.user import AuthEvent, Session as UserSession, User, UserRole
from app.services.security import (
    create_access_token, generate_refresh_token, hash_password,
    hash_refresh_token, refresh_days_for, refresh_expires_at, verify_password,
)


router = APIRouter()

# Refresh-rotation grace window. After a session is rotated, its now-previous
# refresh token is accepted exactly once within this many seconds, so a refresh
# response lost to a network drop or app suspension doesn't sign the user out.
# See app/models/user.py Session.rotated_at / grace_used.
ROTATION_GRACE_SECONDS = 60


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat a stored session timestamp as UTC-aware.

    Postgres (timezone=True columns) hands these back tz-aware; SQLite (tests)
    hands them back naive. Normalizing here keeps the grace/expiry arithmetic
    from tripping over naive-vs-aware comparisons regardless of backend.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

# Precomputed bcrypt hash of a random string. Used to run a constant-time
# verify against unknown usernames so timing doesn't distinguish unknown
# users from wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


# ---------------------------------------------------------------------------
# Login throttle (SEC-P1-4)
# ---------------------------------------------------------------------------
# Durable, proxy-aware throttle in app/services/login_throttle.py. State lives
# in the login_attempts table, so it survives a restart and would coordinate
# across workers. The client IP comes from request.state.client_ip, which is
# honoured only from a trusted proxy peer (SEC-P1-1), so per-IP limits can't be
# dodged with a spoofed header.
def _client_ip(request: Request) -> Optional[str]:
    ip = getattr(request.state, "client_ip", None)
    return ip if ip and ip != "unknown" else None


def _log_auth_event(
    db: Session,
    *,
    user_id: Optional[uuid.UUID],
    event: str,
    request: Request,
) -> None:
    """Append-only auth audit. Does not commit; caller is expected to."""
    ip = getattr(request.state, "client_ip", None)
    ua = request.headers.get("user-agent")
    db.add(
        AuthEvent(
            user_id=user_id,
            event=event,
            ip=ip if ip and ip != "unknown" else None,
            user_agent=ua[:512] if ua else None,
            at=datetime.now(timezone.utc),
        )
    )


def _issue_tokens(
    db: Session,
    *,
    user: User,
    device_label: Optional[str],
    client_type: str = "browser",
    platform: Optional[str] = None,
    client_version: Optional[str] = None,
) -> TokenPair:
    """Create a new sessions row, return access + refresh tokens.

    `client_type` is "browser", "pwa" or "native". PWA sessions get a
    multi-decade refresh TTL so the home-screen icon never asks for
    credentials again; native sessions get a 90-day sliding window that is
    re-stamped on every rotation. `platform` / `client_version` are stored
    on the session for the account screen and the min-version gate.
    """
    refresh_plain = generate_refresh_token()
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_plain),
        device_label=device_label,
        client_type=client_type,
        platform=platform,
        client_version=client_version,
        last_seen_at=datetime.now(timezone.utc),
        expires_at=refresh_expires_at(client_type),
    )
    db.add(session)
    db.flush()  # populate session.id

    access = create_access_token(user.id, user.role.value, session.id)
    return TokenPair(
        access_token=access,
        refresh_token=refresh_plain,
        expires_in_seconds=settings.jwt_access_ttl_minutes * 60,
        refresh_expires_in_seconds=refresh_days_for(client_type) * 86400,
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenPair)
def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenPair:
    username = body.username.lower()
    client_ip = _client_ip(request)

    # Durable throttle: block before touching the password check if this
    # account/IP is over any limit. A blocked attempt is itself recorded, so
    # continued hammering escalates the Retry-After.
    retry = login_throttle.retry_after_for(db, username=username, client_ip=client_ip)
    if retry is not None:
        login_throttle.record_failure(db, username=username, client_ip=client_ip)
        db.commit()
        raise HTTPException(
            status_code=429, detail="too_many_attempts",
            headers={"Retry-After": str(retry)},
        )

    user = db.scalar(select(User).where(User.username == username))
    # Always run verify to keep timing consistent for unknown-vs-wrong-password.
    # _DUMMY_HASH is a valid bcrypt hash of random bytes that nothing will match.
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)

    if not user or not ok or not user.is_active:
        login_throttle.record_failure(db, username=username, client_ip=client_ip)
        _log_auth_event(db, user_id=user.id if user else None,
                        event="login_failed", request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="invalid_credentials")

    login_throttle.clear(db, username=username, client_ip=client_ip)
    # Client type: the body wins (native 2.0 clients send it explicitly);
    # the legacy x-client-type header is the fallback for the web/PWA client.
    # Anything unrecognized collapses to "browser" so its 30-day behavior is
    # the safe default.
    raw_client_type = (
        body.client_type
        or request.headers.get("x-client-type")
        or ""
    ).strip().lower()
    if raw_client_type in ("pwa", "native"):
        client_type = raw_client_type
    else:
        client_type = "browser"
    device_label = body.device_name or body.device_label
    tokens = _issue_tokens(
        db, user=user, device_label=device_label, client_type=client_type,
        platform=body.platform, client_version=body.client_version,
    )
    _log_auth_event(db, user_id=user.id, event="login_success", request=request)
    db.commit()
    return tokens


# ---------------------------------------------------------------------------
# Refresh (rotate)
# ---------------------------------------------------------------------------
@router.post("/refresh", response_model=TokenPair)
def refresh(
    body: RefreshRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenPair:
    token_hash = hash_refresh_token(body.refresh_token)
    session = db.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    )
    now = datetime.now(timezone.utc)
    if session is None:
        # Unknown token — possible leak. Record it but reveal nothing.
        _log_auth_event(db, user_id=None, event="refresh_unknown", request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="invalid_refresh_token")

    if session.revoked_at is not None:
        # Grace window: a session revoked by *rotation* (rotated_at set) whose
        # now-previous token is presented exactly once within
        # ROTATION_GRACE_SECONDS is accepted, so a refresh response lost to a
        # network drop or an app suspension doesn't sign the user out.
        rotated_at = _as_utc(session.rotated_at)
        grace_eligible = (
            rotated_at is not None
            and not session.grace_used
            and (now - rotated_at).total_seconds() <= ROTATION_GRACE_SECONDS
            and _as_utc(session.expires_at) > now
        )
        if grace_eligible:
            user = db.get(User, session.user_id)
            if user is None or not user.is_active:
                session.grace_used = True
                db.commit()
                raise HTTPException(status_code=401, detail="inactive_or_unknown_user")
            # Consume the single grace acceptance, then rotate again to a
            # fresh token so the client is back on a normal chain.
            session.grace_used = True
            tokens = _issue_tokens(
                db, user=user, device_label=session.device_label,
                client_type=session.client_type or "browser",
                platform=session.platform, client_version=session.client_version,
            )
            _log_auth_event(db, user_id=user.id,
                            event="refresh_grace_used", request=request)
            db.commit()
            return tokens

        # Any other revoked token — a second grace use, one presented past the
        # window, or one revoked by logout / password change / admin action
        # (rotated_at is null) — is reuse. Treat as compromise: revoke every
        # active session for the user.
        db.query(UserSession).filter(
            UserSession.user_id == session.user_id,
            UserSession.revoked_at.is_(None),
        ).update({"revoked_at": now})
        _log_auth_event(db, user_id=session.user_id,
                        event="refresh_reuse_detected", request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="refresh_token_revoked")

    if _as_utc(session.expires_at) <= now:
        session.revoked_at = now
        _log_auth_event(db, user_id=session.user_id,
                        event="refresh_expired", request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="refresh_token_expired")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="inactive_or_unknown_user")

    # Rotate: revoke current session, issue a new one. Preserve the original
    # session's client_type so a PWA chain stays PWA and a native chain stays
    # native across rotations (native re-stamps the 90-day window each time),
    # and carry the device metadata forward. `rotated_at` marks this as a
    # rotation revoke so the previous token stays grace-eligible for 60s.
    prior_client_type = session.client_type or "browser"
    session.revoked_at = now
    session.rotated_at = now
    tokens = _issue_tokens(
        db, user=user, device_label=session.device_label,
        client_type=prior_client_type,
        platform=session.platform, client_version=session.client_version,
    )
    _log_auth_event(db, user_id=user.id, event="refresh_rotated", request=request)
    db.commit()
    return tokens


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: LogoutRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    now = datetime.now(timezone.utc)
    if body.refresh_token:
        token_hash = hash_refresh_token(body.refresh_token)
        session = db.scalar(
            select(UserSession).where(
                UserSession.refresh_token_hash == token_hash,
                UserSession.user_id == user.id,
            )
        )
        if session and session.revoked_at is None:
            session.revoked_at = now
        _log_auth_event(db, user_id=user.id, event="logout", request=request)
    else:
        db.query(UserSession).filter(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        ).update({"revoked_at": now})
        _log_auth_event(db, user_id=user.id, event="logout_all", request=request)
    db.commit()


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------
@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdateRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Self-service profile update. Only display_name for now; username is
    immutable here (admins change it via the user-management endpoints)."""
    new_name = body.display_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="display_name_required")
    if new_name != user.display_name:
        user.display_name = new_name
        _log_auth_event(db, user_id=user.id, event="profile_updated", request=request)
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/password", status_code=204)
def change_my_password(
    body: PasswordChangeRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Self-service password change. Requires the current password, then
    rotates all outstanding sessions so other devices must sign in again."""
    if not verify_password(body.current_password, user.password_hash):
        _log_auth_event(db, user_id=user.id, event="password_change_failed",
                        request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="invalid_current_password")
    if body.current_password == body.new_password:
        raise HTTPException(status_code=422, detail="new_password_same_as_current")

    user.password_hash = hash_password(body.new_password)
    # Revoke all outstanding sessions. The client will get a 401 on its next
    # request and the refresh flow will fail too, forcing a fresh login.
    # This is intentional: password change invalidates every device.
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(timezone.utc)})
    _log_auth_event(db, user_id=user.id, event="password_changed", request=request)
    db.commit()


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------
@router.get("/users", response_model=list[UserOut])
def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.role != UserRole.system)
            .order_by(User.created_at)
        )
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreateRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    username = body.username.lower()
    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="username_already_exists")
    user = User(
        username=username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=UserRole(body.role),
    )
    db.add(user)
    db.flush()
    _log_auth_event(db, user_id=admin.id, event=f"admin_created_user:{user.id}",
                    request=request)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Admin edit of a single user: display name, role, and active flag.
    Only fields present in the body are applied."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")

    changes: list[str] = []

    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="display_name_required")
        if name != target.display_name:
            target.display_name = name
            changes.append("display_name")

    if body.role is not None:
        new_role = UserRole(body.role)
        # Guard: cannot strip admin off the last remaining active admin.
        if target.role == UserRole.admin and new_role != UserRole.admin:
            if _count_other_active_admins(db, target.id) == 0:
                raise HTTPException(status_code=409, detail="cannot_demote_last_admin")
        if new_role != target.role:
            target.role = new_role
            changes.append("role")

    if body.is_active is not None and body.is_active != target.is_active:
        # Guard: cannot disable the last remaining active admin.
        if (
            target.role == UserRole.admin
            and not body.is_active
            and _count_other_active_admins(db, target.id) == 0
        ):
            raise HTTPException(status_code=409, detail="cannot_disable_last_admin")
        target.is_active = body.is_active
        changes.append("is_active")
        # Disabling a user should take effect immediately: revoke outstanding
        # sessions so any open tab can't keep replaying its cookie. Re-enable
        # does not re-issue anything; the user just logs in again.
        if not body.is_active:
            db.query(UserSession).filter(
                UserSession.user_id == target.id,
                UserSession.revoked_at.is_(None),
            ).update({"revoked_at": datetime.now(timezone.utc)})

    if changes:
        _log_auth_event(
            db, user_id=admin.id,
            event=f"admin_updated_user:{target.id}:{'+'.join(changes)}",
            request=request,
        )
    db.commit()
    db.refresh(target)
    return target


def _count_other_active_admins(db: Session, exclude_user_id: uuid.UUID) -> int:
    from sqlalchemy import func
    return int(
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == UserRole.admin,
                User.is_active.is_(True),
                User.id != exclude_user_id,
            )
        )
        or 0
    )


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(
    user_id: uuid.UUID,
    body: PasswordResetRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    target.password_hash = hash_password(body.new_password)
    # Revoke all outstanding sessions on password reset.
    db.query(UserSession).filter(
        UserSession.user_id == target.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(timezone.utc)})
    _log_auth_event(db, user_id=admin.id,
                    event=f"admin_reset_password:{target.id}", request=request)
    db.commit()
