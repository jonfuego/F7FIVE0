"""Native 2.0 auth: 90-day sliding refresh, rotation grace window, and proof
that browser and PWA refresh TTLs are unchanged.

These drive the real login/refresh endpoints against the in-memory SQLite DB
from conftest, so token issuance, rotation, and the grace bookkeeping columns
(sessions.rotated_at / grace_used) are all exercised end to end.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.main import app
from app.models.user import Session as UserSession, User, UserRole
from app.services.security import (
    NATIVE_REFRESH_DAYS, PWA_REFRESH_DAYS, hash_password,
)


PASSWORD = "hunter2password"


@pytest.fixture()
def api(db_session):
    """TestClient wired to the test DB session. No lifespan (would dispose the
    StaticPool engine the db_session is bound to), no current_user override
    (login/refresh are unauthenticated)."""
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield client, db_session
    finally:
        client.close()
        app.dependency_overrides.clear()


def _make_user(db, username="native-user"):
    user = User(
        username=username,
        display_name="Native User",
        password_hash=hash_password(PASSWORD),
        role=UserRole.member,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, *, client_type="native", username="native-user"):
    body = {"username": username, "password": PASSWORD}
    if client_type is not None:
        body["client_type"] = client_type
        body["device_name"] = "Pixel Test"
        body["platform"] = "android"
        body["client_version"] = "1.0.0"
    resp = client.post("/api/auth/login", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _aware(dt):
    """SQLite hands back naive datetimes; treat them as UTC for comparison."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _newest_session(db, user_id):
    return (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .order_by(UserSession.created_at.desc(), UserSession.expires_at.desc())
        .first()
    )


def test_native_refresh_is_90_day_sliding(api):
    client, db = api
    user = _make_user(db)

    tokens = _login(client, client_type="native")
    assert tokens["refresh_expires_in_seconds"] == NATIVE_REFRESH_DAYS * 86400

    # Login session carries a ~90-day expiry.
    login_session = _newest_session(db, user.id)
    now = datetime.now(timezone.utc)
    assert _aware(login_session.expires_at) > now + timedelta(days=NATIVE_REFRESH_DAYS - 1)

    # Each refresh re-issues a token with a *fresh* 90-day window (sliding),
    # not a window that counts down from the original login.
    prev_refresh = tokens["refresh_token"]
    for _ in range(2):
        resp = client.post("/api/auth/refresh", json={"refresh_token": prev_refresh})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["refresh_expires_in_seconds"] == NATIVE_REFRESH_DAYS * 86400
        rotated_session = _newest_session(db, user.id)
        assert rotated_session.client_type == "native"
        assert rotated_session.platform == "android"
        assert _aware(rotated_session.expires_at) > datetime.now(timezone.utc) + timedelta(
            days=NATIVE_REFRESH_DAYS - 1
        )
        prev_refresh = body["refresh_token"]


def test_grace_window_accepts_previous_token_once(api):
    client, db = api
    _make_user(db)

    tokens = _login(client, client_type="native")
    original = tokens["refresh_token"]

    # First refresh rotates: `original` is now the previous token.
    first = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200, first.text

    # Re-presenting `original` immediately (well within the 60s grace) is
    # accepted exactly once and returns a fresh, usable token pair.
    grace = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert grace.status_code == 200, grace.text
    assert grace.json()["refresh_token"]

    # A *second* grace use of the same previous token is rejected as reuse.
    second = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert second.status_code == 401
    assert second.json()["detail"] == "refresh_token_revoked"


def test_grace_window_rejects_after_expiry(api):
    client, db = api
    user = _make_user(db)

    tokens = _login(client, client_type="native")
    original = tokens["refresh_token"]

    first = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200, first.text

    # Age the rotated session past the 60s grace window.
    rotated = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.rotated_at.isnot(None))
        .order_by(UserSession.rotated_at.desc())
        .first()
    )
    assert rotated is not None
    rotated.rotated_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    db.commit()

    # Presenting the previous token after the window is treated as reuse.
    late = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert late.status_code == 401
    assert late.json()["detail"] == "refresh_token_revoked"


def test_browser_and_pwa_ttls_unchanged(api):
    client, db = api
    _make_user(db, username="browser-user")
    _make_user(db, username="pwa-user")

    # Browser: explicit client_type omitted -> defaults to browser, 30 days.
    browser = client.post(
        "/api/auth/login",
        json={"username": "browser-user", "password": PASSWORD},
    )
    assert browser.status_code == 200, browser.text
    assert browser.json()["refresh_expires_in_seconds"] == (
        settings.jwt_refresh_ttl_days * 86400
    )

    # PWA: body client_type=pwa keeps the long PWA window.
    pwa = client.post(
        "/api/auth/login",
        json={"username": "pwa-user", "password": PASSWORD, "client_type": "pwa"},
    )
    assert pwa.status_code == 200, pwa.text
    assert pwa.json()["refresh_expires_in_seconds"] == PWA_REFRESH_DAYS * 86400

    # And the legacy x-client-type header path still yields a PWA session.
    pwa_header = client.post(
        "/api/auth/login",
        json={"username": "pwa-user", "password": PASSWORD},
        headers={"x-client-type": "pwa"},
    )
    assert pwa_header.status_code == 200, pwa_header.text
    assert pwa_header.json()["refresh_expires_in_seconds"] == PWA_REFRESH_DAYS * 86400
