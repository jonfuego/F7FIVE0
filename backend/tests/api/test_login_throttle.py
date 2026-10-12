"""SEC-P1-4: durable, proxy-aware login throttle.

Drives the real /api/auth/login endpoint against the in-memory SQLite DB so the
limits, the truthful Retry-After, and the generic-error behaviour are exercised
end to end, plus the service's per-account-across-IPs and per-IP dimensions.

Time is moved by shifting the recorded attempt times back (a stand-in for
waiting), because the endpoint reads the real clock.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_module
from app.api.deps import get_db
from app.main import app
from app.models.login_attempt import LoginAttempt
from app.models.user import User, UserRole
from app.services import login_throttle
from app.services.security import hash_password


PASSWORD = "hunter2password"


@pytest.fixture()
def api(db_session):
    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    try:
        yield c, db_session
    finally:
        c.close()
        app.dependency_overrides.clear()


def _make_user(db, username="throttle-user"):
    u = User(
        username=username, display_name="T",
        password_hash=hash_password(PASSWORD), role=UserRole.member, is_active=True,
    )
    db.add(u)
    db.commit()
    return u


def _bad_login(c, username="throttle-user", cf=None):
    headers = {"cf-connecting-ip": cf} if cf else {}
    return c.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong"},
        headers=headers,
    )


def _good_login(c, username="throttle-user"):
    return c.post("/api/auth/login", json={"username": username, "password": PASSWORD})


def _wait(db, seconds):
    """Let `seconds` pass: every recorded attempt happened that much earlier."""
    for row in db.query(LoginAttempt).all():
        row.at = row.at - timedelta(seconds=seconds)
    db.commit()


def _attempts(db):
    db.expire_all()
    return db.query(LoginAttempt).count()


def test_no_in_memory_throttle_state():
    # The old module-level dict is gone; state is durable (criterion 21).
    assert not hasattr(auth_module, "_login_failures")


def test_blocks_after_limit_and_survives_restart(api):
    c, db = api
    _make_user(db)
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP):
        assert _bad_login(c).status_code == 401
    blocked = _bad_login(c)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "too_many_attempts"
    # The oldest failure is a moment old, so the wait is the whole window.
    retry = int(blocked.headers["Retry-After"])
    assert login_throttle.WINDOW_SECONDS - 5 <= retry <= login_throttle.WINDOW_SECONDS

    # State is table rows, not process memory: a brand-new client (a stand-in
    # for a restarted process) sharing the same DB still sees the block.
    c2 = TestClient(app)
    try:
        assert _bad_login(c2).status_code == 429
    finally:
        c2.close()
    assert db.query(LoginAttempt).count() == login_throttle.MAX_PER_ACCOUNT_IP


def test_correct_password_works_after_waiting_the_returned_retry_after(api):
    c, db = api
    _make_user(db)
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP):
        assert _bad_login(c).status_code == 401
    blocked = _good_login(c)  # even the right password is refused while blocked
    assert blocked.status_code == 429
    retry = int(blocked.headers["Retry-After"])

    _wait(db, retry - 2)  # two seconds early: still blocked, and the wait is two seconds
    early = _good_login(c)
    assert early.status_code == 429
    assert 1 <= int(early.headers["Retry-After"]) <= 3

    _wait(db, 3)  # now past the returned wait
    ok = _good_login(c)
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_token"]


def test_blocked_attempts_do_not_lengthen_the_wait(api):
    c, db = api
    _make_user(db)
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP):
        assert _bad_login(c).status_code == 401
    first = int(_bad_login(c).headers["Retry-After"])
    for _ in range(30):
        assert _bad_login(c).status_code == 429
    for _ in range(5):
        assert _good_login(c).status_code == 429
    last = int(_bad_login(c).headers["Retry-After"])
    assert last <= first
    assert _attempts(db) == login_throttle.MAX_PER_ACCOUNT_IP, "a blocked attempt must not be recorded"


def test_failures_after_the_wait_start_a_fresh_count(api):
    c, db = api
    _make_user(db)
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP):
        _bad_login(c)
    retry = int(_bad_login(c).headers["Retry-After"])
    _wait(db, retry)
    assert _bad_login(c).status_code == 401  # allowed again, recorded as one failure
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=login_throttle.WINDOW_SECONDS)
    in_window = [r for r in db.query(LoginAttempt).all()
                 if (r.at if r.at.tzinfo else r.at.replace(tzinfo=timezone.utc)) > cutoff]
    assert len(in_window) == 1


def test_per_account_limit_across_several_ips(api, monkeypatch):
    c, db = api
    _make_user(db)
    # Trusted peer -> each distinct CF-Connecting-IP is a distinct client IP.
    monkeypatch.setattr("app.services.trusted_proxy.peer_is_trusted", lambda ip: True)
    ips = [f"203.0.113.{i}" for i in range(5)]
    # Spread MAX_PER_ACCOUNT failures across the 5 IPs so no single (account,IP)
    # reaches MAX_PER_ACCOUNT_IP, yet the per-account limit still trips.
    for i in range(login_throttle.MAX_PER_ACCOUNT):
        assert _bad_login(c, cf=ips[i % len(ips)]).status_code == 401
    # A fresh IP for the same account is now blocked by the per-account limit.
    blocked = _bad_login(c, cf="203.0.113.99")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_identical_response_unknown_vs_wrong_password(api):
    c, db = api
    _make_user(db, username="real-user")
    wrong = c.post("/api/auth/login", json={"username": "real-user", "password": "nope"})
    unknown = c.post("/api/auth/login", json={"username": "ghost-user", "password": "nope"})
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_successful_login_clears_the_counter(api):
    c, db = api
    _make_user(db)
    # Four failures (one short of the limit), then a success resets the counter.
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP - 1):
        assert _bad_login(c).status_code == 401
    ok = _good_login(c)
    assert ok.status_code == 200, ok.text
    # The per-(account, IP) rows are gone, so the next failures start fresh.
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP):
        assert _bad_login(c).status_code == 401


# ---------------------------------------------------------------------------
# The Retry-After arithmetic (service level, explicit clock)
# ---------------------------------------------------------------------------
NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def _rows(db, ago_seconds, *, username="u", ip="203.0.113.7"):
    for s in ago_seconds:
        db.add(LoginAttempt(username=username, client_ip=ip, at=NOW - timedelta(seconds=s)))
    db.commit()


def test_not_blocked_below_the_limit(db_session):
    _rows(db_session, [800, 700, 600, 500])  # 4 < 5
    assert login_throttle.retry_after_for(db_session, username="u", client_ip="203.0.113.7", now=NOW) is None


def test_exactly_at_the_limit_waits_for_the_oldest_row(db_session):
    _rows(db_session, [800, 700, 600, 500, 400])  # 5 == limit
    wait = login_throttle.retry_after_for(db_session, username="u", client_ip="203.0.113.7", now=NOW)
    assert wait == 100  # the oldest row (800 s ago) leaves the 900 s window in 100 s


def test_over_the_limit_waits_for_enough_rows_to_leave(db_session):
    # 7 rows, limit 5: the 3 oldest must leave; the third oldest is 700 s old.
    _rows(db_session, [850, 800, 700, 600, 500, 400, 300])
    ip = "203.0.113.7"
    assert login_throttle.retry_after_for(db_session, username="u", client_ip=ip, now=NOW) == 200
    later = NOW + timedelta(seconds=200)
    assert login_throttle.retry_after_for(db_session, username="u", client_ip=ip, now=later) is None
    just_before = NOW + timedelta(seconds=199)
    assert login_throttle.retry_after_for(db_session, username="u", client_ip=ip, now=just_before) == 1


def test_returned_wait_always_unblocks(db_session):
    _rows(db_session, [899, 640.5, 600, 333.3, 12, 11, 10, 9, 8])
    ip = "203.0.113.7"
    wait = login_throttle.retry_after_for(db_session, username="u", client_ip=ip, now=NOW)
    assert isinstance(wait, int) and wait >= 1
    assert login_throttle.retry_after_for(
        db_session, username="u", client_ip=ip, now=NOW + timedelta(seconds=wait)) is None
    assert login_throttle.retry_after_for(
        db_session, username="u", client_ip=ip, now=NOW + timedelta(seconds=wait - 1)) is not None


def test_the_longest_blocked_dimension_sets_the_wait(db_session):
    # (account, IP) is blocked by 5 recent rows (wait 880 s); the account-wide
    # dimension is blocked too (10 rows) and clears sooner or later: take the max.
    ip = "203.0.113.7"
    _rows(db_session, [20, 19, 18, 17, 16], ip=ip)                                   # this IP, recent
    _rows(db_session, [890, 880, 870, 860, 850], ip="198.51.100.9")                  # other IP, old
    wait = login_throttle.retry_after_for(db_session, username="u", client_ip=ip, now=NOW)
    # account-wide: 10 rows, limit 10 -> oldest (890 s) leaves in 10 s
    # (account, IP): 5 rows, limit 5 -> oldest of those (20 s) leaves in 880 s
    assert wait == 880


def test_per_ip_dimension_across_accounts(db_session):
    ip = "203.0.113.7"
    for i in range(login_throttle.MAX_PER_IP):
        db_session.add(LoginAttempt(username=f"user{i}", client_ip=ip, at=NOW - timedelta(seconds=100 + i)))
    db_session.commit()
    wait = login_throttle.retry_after_for(db_session, username="someone-new", client_ip=ip, now=NOW)
    assert wait == 900 - (100 + login_throttle.MAX_PER_IP - 1)


def test_rows_outside_the_window_do_not_count(db_session):
    _rows(db_session, [901, 1200, 5000, 100, 90, 80, 70])
    assert login_throttle.retry_after_for(db_session, username="u", client_ip="203.0.113.7", now=NOW) is None


def test_retry_after_is_whole_seconds_rounded_up(db_session):
    _rows(db_session, [899.2, 600, 500, 400, 300])
    wait = login_throttle.retry_after_for(db_session, username="u", client_ip="203.0.113.7", now=NOW)
    assert wait == math.ceil(900 - 899.2) == 1


# ---------------------------------------------------------------------------
# Per-username serialization
# ---------------------------------------------------------------------------
def test_lock_key_is_stable_and_fits_a_bigint():
    a = login_throttle.lock_key("alice")
    assert a == login_throttle.lock_key("alice")
    assert a != login_throttle.lock_key("bob")
    assert -(2 ** 63) <= a < 2 ** 63


def test_lock_is_a_no_op_on_sqlite(db_session):
    login_throttle.lock_username(db_session, "alice")  # must not run pg-only SQL


def test_lock_takes_a_postgres_advisory_xact_lock():
    from sqlalchemy.dialects import postgresql

    class _Bind:
        dialect = postgresql.dialect()

    class _Db:
        def __init__(self):
            self.calls = []

        def get_bind(self):
            return _Bind()

        def execute(self, stmt, params=None):
            self.calls.append((str(stmt), params))

    db = _Db()
    login_throttle.lock_username(db, "alice")
    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert "pg_advisory_xact_lock" in sql
    assert params == {"k": login_throttle.lock_key("alice")}
