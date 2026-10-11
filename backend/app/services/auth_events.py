"""Auth audit events: the strings, and the one writer.

`auth_events.event` is `String(64)`. PostgreSQL rejects a longer value and the
whole transaction goes with it (SQLite, which the tests use, does not enforce
the length). That is how Admin > Users > Disable once answered HTTP 500: the
event `admin_updated_user:<uuid>:is_active` was 65 characters.

Rules kept here so they stay in one place:

- Every event that carries data (a user id, a client type, a list of changed
  fields) is built by a function in this module. `tests/test_auth_events.py`
  enumerates them with a full 36 character UUID and fails if any is longer than
  the column. Fixed event names are plain string literals at the call sites;
  the same test walks the source and checks each of those too, and fails on an
  event built any other way (an f-string at a call site, for example).
- `record_auth_event` is the only code that inserts an `AuthEvent`. An audit
  write must never fail the request: it runs inside a SAVEPOINT, so a rejected
  insert is rolled back on its own and the caller's transaction (the user
  update, the new session) is still good to commit. On PostgreSQL a failed
  statement aborts the whole transaction; the SAVEPOINT is what stops that. A
  failure is logged (event name and error type only) and swallowed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import AuthEvent

log = logging.getLogger(__name__)

# Read from the model so the limit and the column cannot drift apart.
EVENT_MAX_LEN: int = AuthEvent.__table__.c.event.type.length

# Client types a passkey login can record (see api/passkeys.py).
PASSKEY_CLIENT_TYPES: tuple[str, ...] = ("browser", "pwa", "native")

# Admin edits to a user, in the order update_user reports them, with the short
# code that goes into the event. Short on purpose: all three together plus a
# 36 character user id must fit in EVENT_MAX_LEN.
USER_FIELD_CODES: dict[str, str] = {
    "display_name": "name",
    "role": "role",
    "is_active": "active",
}


def admin_created_user(user_id: uuid.UUID | str) -> str:
    """`admin_created_user:<user id>`: the actor is the row's user_id."""
    return f"admin_created_user:{user_id}"


def admin_reset_password(user_id: uuid.UUID | str) -> str:
    """`admin_reset_password:<user id>`."""
    return f"admin_reset_password:{user_id}"


def admin_updated_user(user_id: uuid.UUID | str, changes: Iterable[str]) -> str:
    """`user_edit:<user id>:name+role+active` (any subset, in that order).

    Older rows read `admin_updated_user:<user id>:<field names>`; they stay as
    they are. The target user id stays in the event because the row's user_id
    column holds the admin who made the change.
    """
    codes = "+".join(USER_FIELD_CODES.get(c, c[:8]) for c in changes)
    return f"user_edit:{user_id}:{codes}"


def passkey_login(client_type: str) -> str:
    """`passkey_login:<browser|pwa|native>`; `passkey_login` is the grep prefix."""
    return f"passkey_login:{client_type}"


def fit_event(event: str) -> str:
    """Last-resort guard: never hand the database a value it will reject."""
    if len(event) <= EVENT_MAX_LEN:
        return event
    log.warning("auth event too long (%d chars), truncated: %s", len(event), event[:48])
    return event[:EVENT_MAX_LEN]


def _build_row(
    *, user_id: Optional[uuid.UUID], event: str, request: Request,
) -> AuthEvent:
    ip = getattr(request.state, "client_ip", None)
    ua = request.headers.get("user-agent")
    return AuthEvent(
        user_id=user_id,
        event=fit_event(event),
        ip=ip if ip and ip != "unknown" else None,
        user_agent=ua[:512] if ua else None,
        at=datetime.now(timezone.utc),
    )


def record_auth_event(
    db: Session,
    *,
    user_id: Optional[uuid.UUID],
    event: str,
    request: Request,
) -> bool:
    """Append an auth audit row. Does not commit; the caller does.

    Returns True when the row was written, False when the write failed and was
    swallowed. Never raises for an audit problem.
    """
    # Send the caller's pending changes first, outside the guard: if those are
    # what fail, that is a real error and must reach the caller. begin_nested()
    # would flush them anyway.
    db.flush()
    try:
        with db.begin_nested():
            db.add(_build_row(user_id=user_id, event=event, request=request))
    except Exception as exc:  # noqa: BLE001 - the audit must not fail the request
        # Event name and error type only: the exception text can carry SQL
        # parameters (address, user agent).
        log.warning(
            "auth audit write failed (event=%s, error=%s); request continues",
            str(event)[:80], type(exc).__name__,
        )
        return False
    return True
