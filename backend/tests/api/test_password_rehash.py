"""Signing in replaces a legacy bcrypt hash with argon2id (api/auth.py login).

Existing installs hold bcrypt-over-SHA-256 hashes. They must keep working, and
the first good sign-in stores argon2id. A wrong password, an inactive account
or a throttled attempt never touches the stored hash.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app
from app.models.user import User, UserRole
from app.services.security import verify_password

PASSWORD = "hunter2password"
# Made by the pre-argon2 code: bcrypt (cost 4) over a base64 SHA-256 of PASSWORD.
OLD_HASH = "$2b$04$0XvSBcB8HuRA8WLsC82Q5uPO.O/hSvRwNAUYyndB0VjV2TNzJpH8a"


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


def _legacy_user(db, username="legacy-user", active=True):
    u = User(username=username, display_name="L", password_hash=OLD_HASH,
             role=UserRole.member, is_active=active)
    db.add(u)
    db.commit()
    return u


def _login(c, username="legacy-user", password=PASSWORD):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def test_a_legacy_hash_signs_in_and_is_upgraded(api):
    c, db = api
    u = _legacy_user(db)
    assert _login(c).status_code == 200

    db.refresh(u)
    assert u.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, u.password_hash)
    # The new hash works for the next sign-in, and is not replaced again.
    upgraded = u.password_hash
    assert _login(c).status_code == 200
    db.refresh(u)
    assert u.password_hash == upgraded


def test_a_wrong_password_leaves_the_legacy_hash(api):
    c, db = api
    u = _legacy_user(db)
    before = u.password_hash
    assert _login(c, password="not-it").status_code == 401
    db.refresh(u)
    assert u.password_hash == before


def test_an_inactive_account_is_not_upgraded(api):
    c, db = api
    u = _legacy_user(db, active=False)
    before = u.password_hash
    assert _login(c).status_code == 401
    db.refresh(u)
    assert u.password_hash == before


def test_an_unknown_user_still_gets_the_generic_401(api):
    c, _ = api
    r = _login(c, username="nobody-here")
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"
