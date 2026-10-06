"""SEC-P1-3: installed-PWA refresh sessions are capped at a 90-day sliding
window (was ~10 years), rotated on every refresh. A leaked PWA refresh token
is now good for at most 90 days, and an existing long-lived PWA session is
capped the next time it refreshes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.user import Session as UserSession, User, UserRole
from app.services.security import PWA_REFRESH_DAYS, hash_password


PASSWORD = "hunter2password"


@pytest.fixture()
def api(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield client, db_session
    finally:
        client.close()
        app.dependency_overrides.clear()


def _make_user(db, username="pwa-user"):
    user = User(
        username=username,
        display_name="PWA User",
        password_hash=hash_password(PASSWORD),
        role=UserRole.member,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def _aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _newest_session(db, user_id):
    return (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .order_by(UserSession.created_at.desc(), UserSession.expires_at.desc())
        .first()
    )


def _login_pwa(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "pwa-user", "password": PASSWORD, "client_type": "pwa"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pwa_refresh_window_is_90_days():
    assert PWA_REFRESH_DAYS == 90


def test_new_pwa_session_expires_in_90_days(api):
    client, db = api
    user = _make_user(db)
    tokens = _login_pwa(client)
    assert tokens["refresh_expires_in_seconds"] == 90 * 86400
    sess = _newest_session(db, user.id)
    now = datetime.now(timezone.utc)
    assert _aware(sess.expires_at) > now + timedelta(days=89)
    assert _aware(sess.expires_at) < now + timedelta(days=91)


def test_pwa_refresh_slides_and_rotates(api):
    client, db = api
    user = _make_user(db)
    tokens = _login_pwa(client)
    prev = tokens["refresh_token"]

    resp = client.post("/api/auth/refresh", json={"refresh_token": prev})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Rotated to a new token with a fresh 90-day window.
    assert body["refresh_token"] != prev
    assert body["refresh_expires_in_seconds"] == 90 * 86400
    rotated = _newest_session(db, user.id)
    assert rotated.client_type == "pwa"
    now = datetime.now(timezone.utc)
    assert _aware(rotated.expires_at) > now + timedelta(days=89)


def test_existing_long_pwa_session_is_capped_on_refresh(api):
    client, db = api
    user = _make_user(db)
    tokens = _login_pwa(client)
    refresh_token = tokens["refresh_token"]

    # Simulate a session issued under the old ~10-year PWA policy.
    sess = _newest_session(db, user.id)
    sess.expires_at = datetime.now(timezone.utc) + timedelta(days=3650)
    db.commit()

    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, resp.text

    # The refreshed (active, non-revoked) session, not the old rotated one.
    capped = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.created_at.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    # The refreshed session is back inside the 90-day cap, not the 10-year one.
    assert _aware(capped.expires_at) < now + timedelta(days=91)
    assert _aware(capped.expires_at) > now + timedelta(days=89)
