"""The 120 s access-token grace belongs to refresh rotation only.

An explicit revoke (logout, logout-all, password change, admin revoke or
disable, refresh-reuse detection) rejects the next request at once. A session
revoked by rotation keeps working for the grace window, so a request already in
flight when the app refreshes does not 401. These drive the real endpoints with
real bearer tokens (no current_user override) and prime the session micro-cache
first, so they also prove the cache is evicted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.db import get_db
from app.main import app
from app.models.user import Session as UserSession, User, UserRole
from app.services.security import hash_password

PASSWORD = "hunter2password"
NEW_PASSWORD = "a-brand-new-password-1"


@pytest.fixture(autouse=True)
def _clean_cache():
    deps._session_cache.clear()
    yield
    deps._session_cache.clear()


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


def _user(db, name="grace-user", role=UserRole.member):
    u = User(username=name, display_name=name, password_hash=hash_password(PASSWORD),
             role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


def _login(client, name="grace-user"):
    r = client.post("/api/auth/login", json={
        "username": name, "password": PASSWORD, "client_type": "native",
        "device_name": name, "platform": "android", "client_version": "1.0.0",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _me(client, tokens):
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})


def _session_of(db, user, refresh_token):
    from app.services.security import hash_refresh_token

    db.expire_all()
    return db.query(UserSession).filter(
        UserSession.refresh_token_hash == hash_refresh_token(refresh_token),
        UserSession.user_id == user.id,
    ).one()


def test_access_token_fails_right_after_logout(api):
    client, db = api
    _user(db)
    tokens = _login(client)
    assert _me(client, tokens).status_code == 200  # primes the micro-cache
    out = client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]},
                      headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert out.status_code == 204, out.text
    after = _me(client, tokens)
    assert after.status_code == 401
    assert after.json()["detail"] == "session_revoked"


def test_access_token_fails_right_after_logout_all(api):
    client, db = api
    _user(db)
    phone, tablet = _login(client), _login(client)
    assert _me(client, phone).status_code == 200 and _me(client, tablet).status_code == 200
    out = client.post("/api/auth/logout", json={},
                      headers={"Authorization": f"Bearer {phone['access_token']}"})
    assert out.status_code == 204, out.text
    for tokens in (phone, tablet):
        r = _me(client, tokens)
        assert r.status_code == 401 and r.json()["detail"] == "session_revoked"


def test_access_token_fails_right_after_a_password_change_on_another_device(api):
    client, db = api
    _user(db)
    laptop, phone = _login(client), _login(client)
    assert _me(client, laptop).status_code == 200 and _me(client, phone).status_code == 200
    change = client.post(
        "/api/auth/me/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {phone['access_token']}"},
    )
    assert change.status_code == 204, change.text
    r = _me(client, laptop)
    assert r.status_code == 401 and r.json()["detail"] == "session_revoked"
    assert _me(client, phone).status_code == 401  # the changing device signs in again too


def test_access_token_of_a_rotated_session_still_works_inside_the_grace(api):
    client, db = api
    user = _user(db)
    old = _login(client)
    assert _me(client, old).status_code == 200
    new = client.post("/api/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert new.status_code == 200, new.text
    spent = _session_of(db, user, old["refresh_token"])
    assert spent.revoked_at is not None and spent.rotated_at is not None

    # Right after the refresh, and 100 s later, the old access token is fine.
    assert _me(client, old).status_code == 200
    spent.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=100)
    db.commit()
    deps.evict_session_cache(spent.id)
    assert _me(client, old).status_code == 200

    # Past the 120 s window it is rejected.
    spent.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=125)
    db.commit()
    deps.evict_session_cache(spent.id)
    late = _me(client, old)
    assert late.status_code == 401 and late.json()["detail"] == "session_revoked"


def test_the_new_token_after_a_rotation_keeps_working(api):
    client, db = api
    _user(db)
    old = _login(client)
    new = client.post("/api/auth/refresh", json={"refresh_token": old["refresh_token"]}).json()
    assert _me(client, new).status_code == 200


def test_refresh_reuse_kills_every_session_at_once(api):
    client, db = api
    user = _user(db)
    stolen_chain = _login(client)
    other_device = _login(client)
    assert _me(client, other_device).status_code == 200  # cached as active
    first = client.post("/api/auth/refresh", json={"refresh_token": stolen_chain["refresh_token"]})
    assert first.status_code == 200
    client.post("/api/auth/refresh", json={"refresh_token": stolen_chain["refresh_token"]})  # the one grace use
    spent = _session_of(db, user, stolen_chain["refresh_token"])
    assert spent.grace_used is True
    reuse = client.post("/api/auth/refresh", json={"refresh_token": stolen_chain["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["detail"] == "refresh_token_revoked"
    r = _me(client, other_device)
    assert r.status_code == 401 and r.json()["detail"] == "session_revoked"
    assert _me(client, first.json()).status_code == 401


def test_admin_disable_and_admin_revoke_take_effect_at_once(api):
    client, db = api
    _user(db, "boss", role=UserRole.admin)
    victim = _user(db, "victim")
    boss_tokens = _login(client, "boss")
    v1, v2 = _login(client, "victim"), _login(client, "victim")
    assert _me(client, v1).status_code == 200 and _me(client, v2).status_code == 200
    auth = {"Authorization": f"Bearer {boss_tokens['access_token']}"}

    sid = _session_of(db, victim, v1["refresh_token"]).id
    assert client.delete(f"/api/admin/sessions/{sid}", headers=auth).status_code == 204
    r = _me(client, v1)
    assert r.status_code == 401 and r.json()["detail"] == "session_revoked"

    off = client.patch(f"/api/auth/users/{victim.id}", json={"is_active": False}, headers=auth)
    assert off.status_code == 200, off.text
    r = _me(client, v2)
    assert r.status_code == 401 and r.json()["detail"] == "session_revoked"


def test_the_cache_keeps_rotated_at(api):
    client, db = api
    user = _user(db)
    old = _login(client)
    client.post("/api/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert _me(client, old).status_code == 200
    spent = _session_of(db, user, old["refresh_token"])
    entry = deps._session_cache[spent.id]
    revoked_at, rotated_at, expires_at, sess_user_id, cached_at = entry
    assert revoked_at is not None and rotated_at is not None
    assert sess_user_id == user.id
