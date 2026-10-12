"""Single-use auth transitions are conditional UPDATEs, not read-then-write.

SQLite cannot run two requests at once, so these put the "other request" in the
gap: a wrapper around the lookup lets a competing writer take the row after the
handler has read it and before the handler claims it. The real concurrency run
against PostgreSQL is tests/test_pg_concurrency.py (opt-in).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.db import get_db
from app.main import app

from app.models.user import AuthEvent, Session as UserSession, User, UserRole
from app.services.security import hash_password

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


def _user(db, name="racer"):
    u = User(username=name, display_name=name, password_hash=hash_password(PASSWORD),
             role=UserRole.member, is_active=True)
    db.add(u)
    db.commit()
    return u


def _login(client, name="racer"):
    r = client.post("/api/auth/login", json={
        "username": name, "password": PASSWORD, "client_type": "native",
        "device_name": "Pixel", "platform": "android", "client_version": "1.0.0",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _sessions(db, user):
    db.expire_all()
    return list(db.scalars(select(UserSession).where(UserSession.user_id == user.id)))


def _events(db, name):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(AuthEvent).where(AuthEvent.event == name))


def _race_on_user_lookup(db, monkeypatch, competing_write):
    """Run `competing_write()` once, right after the handler looks the user up
    (that is after it read the session and before it claims it)."""
    real_get = db.get
    fired = {"n": 0}

    def get(model, ident, *a, **kw):
        row = real_get(model, ident, *a, **kw)
        if model is User and not fired["n"]:
            fired["n"] = 1
            competing_write()
        return row

    monkeypatch.setattr(db, "get", get)
    return fired


def test_rotation_loser_takes_the_reuse_path_and_mints_nothing(api, monkeypatch):
    client, db = api
    user = _user(db)
    token = _login(client)["refresh_token"]
    (only,) = _sessions(db, user)
    now = datetime.now(timezone.utc)

    # The winner rotates this session between the loser's read and its claim.
    def winner_takes_it():
        db.execute(update(UserSession).where(UserSession.id == only.id)
                   .values(revoked_at=now, rotated_at=now))
        db.add(UserSession(user_id=user.id, refresh_token_hash="winner-successor",
                           client_type="native",
                           expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                           last_seen_at=now))
        db.flush()

    fired = _race_on_user_lookup(db, monkeypatch, winner_takes_it)
    resp = client.post("/api/auth/refresh", json={"refresh_token": token})
    assert fired["n"] == 1
    assert resp.status_code == 401
    assert resp.json()["detail"] == "refresh_token_revoked"

    rows = _sessions(db, user)
    assert len(rows) == 2, "the loser must not mint a successor"
    assert all(r.revoked_at is not None for r in rows), "reuse revokes every active session"
    assert _events(db, "refresh_reuse_detected") == 1
    assert _events(db, "refresh_rotated") == 0


def test_a_single_refresh_still_rotates_exactly_once(api):
    client, db = api
    user = _user(db)
    token = _login(client)["refresh_token"]
    r = client.post("/api/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 200, r.text
    rows = _sessions(db, user)
    assert len(rows) == 2
    old = [x for x in rows if x.revoked_at is not None]
    new = [x for x in rows if x.revoked_at is None]
    assert len(old) == 1 and len(new) == 1
    assert old[0].rotated_at is not None and old[0].grace_used is False
    assert _events(db, "refresh_rotated") == 1


def test_grace_loser_takes_the_reuse_path_and_mints_nothing(api, monkeypatch):
    client, db = api
    user = _user(db)
    original = _login(client)["refresh_token"]
    assert client.post("/api/auth/refresh", json={"refresh_token": original}).status_code == 200
    before = len(_sessions(db, user))
    spent = next(s for s in _sessions(db, user) if s.rotated_at is not None)

    # Another request spends the single grace use between read and claim.
    def other_takes_grace():
        db.execute(update(UserSession).where(UserSession.id == spent.id).values(grace_used=True))
        db.flush()

    fired = _race_on_user_lookup(db, monkeypatch, other_takes_grace)
    resp = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert fired["n"] == 1
    assert resp.status_code == 401
    assert resp.json()["detail"] == "refresh_token_revoked"
    rows = _sessions(db, user)
    assert len(rows) == before, "the grace loser must not mint a successor"
    assert all(r.revoked_at is not None for r in rows)
    assert _events(db, "refresh_grace_used") == 0
    assert _events(db, "refresh_reuse_detected") == 1


def test_grace_still_works_once_when_nobody_races(api):
    client, db = api
    user = _user(db)
    original = _login(client)["refresh_token"]
    assert client.post("/api/auth/refresh", json={"refresh_token": original}).status_code == 200
    grace = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert grace.status_code == 200, grace.text
    spent = next(s for s in _sessions(db, user) if s.rotated_at is not None)
    assert spent.grace_used is True
    assert _events(db, "refresh_grace_used") == 1
    assert client.post("/api/auth/refresh", json={"refresh_token": original}).status_code == 401


def test_refresh_source_uses_conditional_updates():
    """The claim must be a conditional UPDATE, not a read followed by a write."""
    import inspect
    from app.api import auth

    src = inspect.getsource(auth.refresh)
    assert "revoked_at.is_(None)" in src and "returning(UserSession.id)" in src
    assert "grace_used.is_(False)" in src
