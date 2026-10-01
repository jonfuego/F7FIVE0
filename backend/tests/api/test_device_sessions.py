"""Self-service device-session endpoints: list (flag current), revoke one,
revoke all-but-current, and cross-user isolation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import current_session_id, current_user, get_db
from app.main import app
from app.models.user import Session as UserSession, User
from app.services.security import hash_password


def _mk_user(db, username):
    u = User(
        username=username, display_name=username.title(),
        password_hash=hash_password("x-strong-pass"), role="member", is_active=True,
    )
    db.add(u)
    db.commit()
    return u


def _mk_session(db, user, label, **kw):
    now = datetime.now(timezone.utc)
    s = UserSession(
        user_id=user.id,
        refresh_token_hash=uuid.uuid4().hex,
        device_label=label,
        client_type=kw.get("client_type", "native"),
        platform=kw.get("platform", "android"),
        client_version=kw.get("client_version", "1.0.0"),
        last_seen_at=now,
        expires_at=now + timedelta(days=90),
        revoked_at=kw.get("revoked_at"),
    )
    db.add(s)
    db.commit()
    return s


@pytest.fixture()
def api(db_session):
    user = _mk_user(db_session, "device-user")
    # Three active sessions; the middle one is "current".
    s_current = _mk_session(db_session, user, "Pixel 8")
    s_other = _mk_session(db_session, user, "Living Room TV", platform="android_tv")
    s_third = _mk_session(db_session, user, "Old Phone")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_session_id] = lambda: s_current.id

    client = TestClient(app)
    try:
        yield client, db_session, user, (s_current, s_other, s_third)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_list_flags_current_session(api):
    client, db, user, (s_current, s_other, s_third) = api
    resp = client.get("/api/sessions")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 3
    by_id = {r["id"]: r for r in rows}
    assert by_id[str(s_current.id)]["current"] is True
    assert by_id[str(s_other.id)]["current"] is False
    # Device metadata is surfaced; no token material is present.
    assert by_id[str(s_other.id)]["platform"] == "android_tv"
    assert all("refresh_token" not in r and "refresh_token_hash" not in r for r in rows)


def test_revoke_one_of_mine(api):
    client, db, user, (s_current, s_other, s_third) = api
    resp = client.delete(f"/api/sessions/{s_other.id}")
    assert resp.status_code == 204, resp.text
    db.refresh(s_other)
    assert s_other.revoked_at is not None
    # The listing now omits the revoked one.
    remaining = {r["id"] for r in client.get("/api/sessions").json()}
    assert str(s_other.id) not in remaining
    assert str(s_current.id) in remaining


def test_revoke_all_but_current(api):
    client, db, user, (s_current, s_other, s_third) = api
    resp = client.delete("/api/sessions")
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked"] == 2
    db.refresh(s_current)
    db.refresh(s_other)
    db.refresh(s_third)
    assert s_current.revoked_at is None
    assert s_other.revoked_at is not None
    assert s_third.revoked_at is not None


def test_cannot_revoke_another_users_session(api):
    client, db, user, _ = api
    stranger = _mk_user(db, "stranger")
    stranger_session = _mk_session(db, stranger, "Not Yours")
    resp = client.delete(f"/api/sessions/{stranger_session.id}")
    assert resp.status_code == 404
    db.refresh(stranger_session)
    assert stranger_session.revoked_at is None
