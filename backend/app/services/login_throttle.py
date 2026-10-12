"""SEC-P1-4: durable, proxy-aware login throttle.

Replaces the in-process failed-login dict. Every failed login attempt is
recorded as a `login_attempts` row; the limits are evaluated by counting rows in
a sliding window across three dimensions:

- (account, client IP)  -- the common case, a single attacker on one account
- (account, all IPs)    -- distributed spray against one account
- (client IP, all accounts) -- one IP spraying many accounts

Because the state lives in the DB, it survives a restart and would coordinate
across workers. The client IP comes from `request.state.client_ip`, which
app/services/trusted_proxy.py set only from a trusted peer (SEC-P1-1), so the
per-IP limits can't be dodged with a spoofed `CF-Connecting-IP`.

`Retry-After` is the real time until the request would be allowed: for every
dimension that is over its limit, the moment enough of its oldest rows have left
the window to bring the count back under the limit, and the latest of those
moments when more than one dimension is blocking. Waiting that long and then
signing in with the right password works. An attempt made while blocked is not
recorded, so hammering a locked account never pushes the time later.

The login endpoint returns the same generic error for an unknown user and a
wrong password, and records a failure either way, so the throttle is not a
username oracle.

Check-and-record is serialized per username on PostgreSQL (`lock_username`, a
transaction-scoped advisory lock), so a burst of parallel attempts cannot all
read the count before any of them records a failure. SQLite (tests, single
connection) needs no lock and gets a no-op.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.login_attempt import LoginAttempt


# Sliding window the counts are evaluated over.
WINDOW_SECONDS = 15 * 60

# Per-dimension failure ceilings within the window.
MAX_PER_ACCOUNT_IP = 5    # one account from one IP
MAX_PER_ACCOUNT = 10      # one account across all IPs (distributed spray)
MAX_PER_IP = 20           # one IP across all accounts (spraying many accounts)


def _cutoff(now: datetime) -> datetime:
    return now - timedelta(seconds=WINDOW_SECONDS)


def _as_utc(dt: datetime) -> datetime:
    """SQLite (tests) hands datetimes back naive; PostgreSQL hands them back aware."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def lock_key(username: str) -> int:
    """A stable signed 64-bit key for `username`, for pg_advisory_xact_lock."""
    digest = hashlib.sha256(("f7five0-login-throttle:" + username).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def lock_username(db: Session, username: str) -> None:
    """Serialize check-and-record for `username` until this transaction ends.

    PostgreSQL: `pg_advisory_xact_lock` on a stable hash of the name; a second
    request for the same name waits here until the first commits or rolls back.
    Other databases (SQLite in tests): a no-op. Call it before
    `retry_after_for`, and keep the transaction open through `record_failure`.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key(username)})


def _where(now: datetime, username: Optional[str], client_ip: Optional[str]):
    clauses = [LoginAttempt.at > _cutoff(now)]
    if username is not None:
        clauses.append(LoginAttempt.username == username)
    if client_ip is not None:
        clauses.append(LoginAttempt.client_ip == client_ip)
    return clauses


def _wait_seconds(db: Session, now: datetime, limit: int, *,
                  username: Optional[str] = None,
                  client_ip: Optional[str] = None) -> Optional[float]:
    """Seconds until this dimension is back under `limit`, or None if it is not
    over it. With `count` rows in the window, the (count - limit + 1) oldest
    must leave; the last of them to leave sets the time."""
    where = _where(now, username, client_ip)
    count = int(db.scalar(select(func.count()).select_from(LoginAttempt).where(*where)) or 0)
    if count < limit:
        return None
    pivot = db.scalar(
        select(LoginAttempt.at).where(*where)
        .order_by(LoginAttempt.at.asc())
        .offset(count - limit)
        .limit(1)
    )
    if pivot is None:  # rows vanished between the two reads; nothing blocks now
        return None
    return (_as_utc(pivot) + timedelta(seconds=WINDOW_SECONDS) - now).total_seconds()


def retry_after_for(db: Session, *, username: str, client_ip: Optional[str],
                    now: Optional[datetime] = None) -> Optional[int]:
    """Whole seconds this (username, ip) must wait if it is over any limit, else
    None. Waiting this long (from `now`) makes the same request succeed."""
    now = now or datetime.now(timezone.utc)
    waits = [_wait_seconds(db, now, MAX_PER_ACCOUNT, username=username)]
    if client_ip:
        waits.append(_wait_seconds(db, now, MAX_PER_ACCOUNT_IP, username=username, client_ip=client_ip))
        waits.append(_wait_seconds(db, now, MAX_PER_IP, client_ip=client_ip))
    blocking = [w for w in waits if w is not None]
    if not blocking:
        return None
    return max(1, math.ceil(max(blocking)))


def record_failure(db: Session, *, username: str, client_ip: Optional[str],
                   now: Optional[datetime] = None) -> None:
    """Record one failed attempt. Does not commit; the caller does. Never call
    it for an attempt that was refused because the caller is blocked."""
    now = now or datetime.now(timezone.utc)
    db.add(LoginAttempt(username=username, client_ip=client_ip, at=now))


def clear(db: Session, *, username: str, client_ip: Optional[str]) -> None:
    """A successful login clears this account's failure rows for this IP, so a
    legitimate sign-in resets the per-(account, IP) counter. Does not commit."""
    db.query(LoginAttempt).filter(
        LoginAttempt.username == username,
        LoginAttempt.client_ip == client_ip,
    ).delete(synchronize_session=False)
