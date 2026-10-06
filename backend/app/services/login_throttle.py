"""SEC-P1-4: durable, proxy-aware login throttle.

Replaces the in-process failed-login dict. Every failed or blocked login
attempt is recorded as a `login_attempts` row; the limits are evaluated by
counting rows in a sliding window across three dimensions:

- (account, client IP)  -- the common case, a single attacker on one account
- (account, all IPs)    -- distributed spray against one account
- (client IP, all accounts) -- one IP spraying many accounts

Because the state lives in the DB, it survives a restart and would coordinate
across workers. The client IP comes from `request.state.client_ip`, which
app/services/trusted_proxy.py set only from a trusted peer (SEC-P1-1), so the
per-IP limits can't be dodged with a spoofed `CF-Connecting-IP`.

Retry-After escalates: the more an account/IP keeps failing (or keeps hammering
while locked), the longer it has to wait, capped at an hour. The login endpoint
returns the same generic error for an unknown user and a wrong password, and
records a failure either way, so the throttle is not a username oracle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.login_attempt import LoginAttempt


# Sliding window the counts are evaluated over.
WINDOW_SECONDS = 15 * 60

# Per-dimension failure ceilings within the window.
MAX_PER_ACCOUNT_IP = 5    # one account from one IP
MAX_PER_ACCOUNT = 10      # one account across all IPs (distributed spray)
MAX_PER_IP = 20           # one IP across all accounts (spraying many accounts)

# Retry-After grows with each full multiple of a limit that is exceeded.
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 3600


def _cutoff(now: datetime) -> datetime:
    return now - timedelta(seconds=WINDOW_SECONDS)


def _count(db: Session, now: datetime, *, username: Optional[str] = None,
           client_ip: Optional[str] = None) -> int:
    q = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.at > _cutoff(now)
    )
    if username is not None:
        q = q.where(LoginAttempt.username == username)
    if client_ip is not None:
        q = q.where(LoginAttempt.client_ip == client_ip)
    return int(db.scalar(q) or 0)


def retry_after_for(db: Session, *, username: str, client_ip: Optional[str],
                    now: Optional[datetime] = None) -> Optional[int]:
    """Seconds this (username, ip) must wait if it is over any limit, else None.

    The returned delay escalates with how far over the worst dimension is, so a
    client that keeps hammering a locked account waits progressively longer.
    """
    now = now or datetime.now(timezone.utc)
    dims: list[tuple[int, int]] = [
        (_count(db, now, username=username), MAX_PER_ACCOUNT),
    ]
    if client_ip:
        dims.append((_count(db, now, username=username, client_ip=client_ip), MAX_PER_ACCOUNT_IP))
        dims.append((_count(db, now, client_ip=client_ip), MAX_PER_IP))

    steps = 0
    for count, limit in dims:
        if count >= limit:
            steps = max(steps, count // limit)
    if steps == 0:
        return None
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (steps - 1)))


def record_failure(db: Session, *, username: str, client_ip: Optional[str],
                   now: Optional[datetime] = None) -> None:
    """Record one failed or blocked attempt. Does not commit; the caller does."""
    now = now or datetime.now(timezone.utc)
    db.add(LoginAttempt(username=username, client_ip=client_ip, at=now))


def clear(db: Session, *, username: str, client_ip: Optional[str]) -> None:
    """A successful login clears this account's failure rows for this IP, so a
    legitimate sign-in resets the per-(account, IP) counter. Does not commit."""
    db.query(LoginAttempt).filter(
        LoginAttempt.username == username,
        LoginAttempt.client_ip == client_ip,
    ).delete(synchronize_session=False)
