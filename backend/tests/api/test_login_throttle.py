"""SEC-P1-4: durable, proxy-aware login throttle.

Drives the real /api/auth/login endpoint against the in-memory SQLite DB so the
limits, escalation, and generic-error behaviour are exercised end to end, plus
the service's per-account-across-IPs dimension.
"""
from __future__ import annotations

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
    assert int(blocked.headers["Retry-After"]) >= login_throttle.RETRY_BASE_SECONDS

    # State is table rows, not process memory: a brand-new client (a stand-in
    # for a restarted process) sharing the same DB still sees the block.
    c2 = TestClient(app)
    try:
        assert _bad_login(c2).status_code == 429
    finally:
        c2.close()
    assert db.query(LoginAttempt).count() >= login_throttle.MAX_PER_ACCOUNT_IP


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


def test_retry_after_escalates(api):
    c, db = api
    _make_user(db)
    retries = []
    for _ in range(3 * login_throttle.MAX_PER_ACCOUNT_IP):
        r = _bad_login(c)
        if r.status_code == 429:
            retries.append(int(r.headers["Retry-After"]))
    assert retries, "expected the account to get throttled"
    # The longer the hammering continues, the longer the wait.
    assert max(retries) > min(retries)
    assert max(retries) >= login_throttle.RETRY_BASE_SECONDS * 2


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
    ok = c.post("/api/auth/login", json={"username": "throttle-user", "password": PASSWORD})
    assert ok.status_code == 200, ok.text
    # The per-(account, IP) rows are gone, so the next failures start fresh.
    for _ in range(login_throttle.MAX_PER_ACCOUNT_IP):
        assert _bad_login(c).status_code == 401
