"""First-run admin from the browser (app/api/setup.py).

Open only while the server has no account, and only to a browser on the server
PC (the real client IP is loopback). The TestClient's `client=` sets the socket
peer; the IP middleware turns it into `request.state.client_ip`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models.user import AuthEvent, User, UserRole
from app.services.security import verify_password

LOCAL = ("127.0.0.1", 50000)
LAN = ("192.168.1.50", 50000)
GOOD = {"username": "Jon", "password": "longenoughpw", "display_name": "Jon"}


@pytest.fixture()
def make_client(db_session):
    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    made: list[TestClient] = []

    def _make(peer=LOCAL, headers=None):
        c = TestClient(app, client=peer, headers=headers or {})
        made.append(c)
        return c

    yield _make
    for c in made:
        c.close()
    app.dependency_overrides.clear()


def test_state_says_an_admin_is_needed_on_a_fresh_server(make_client):
    r = make_client().get("/api/setup/state")
    assert r.status_code == 200
    assert r.json() == {"needs_admin": True, "local": True}


def test_state_from_the_lan_is_not_local(make_client):
    assert make_client(LAN).get("/api/setup/state").json() == {"needs_admin": True, "local": False}


def test_the_seeded_system_user_does_not_count(make_client, db_session):
    db_session.add(User(username="system", display_name="System", password_hash="x",
                        role=UserRole.system, is_active=False))
    db_session.commit()
    assert make_client().get("/api/setup/state").json()["needs_admin"] is True


def test_a_local_browser_creates_the_first_admin_who_can_sign_in(make_client, db_session):
    c = make_client()
    r = c.post("/api/setup/admin", json=GOOD)
    assert r.status_code == 201, r.text
    assert r.json() == {"username": "jon"}

    user = db_session.scalar(select(User).where(User.username == "jon"))
    assert user is not None and user.role == UserRole.admin and user.is_active
    assert verify_password("longenoughpw", user.password_hash)
    assert db_session.scalar(select(AuthEvent).where(AuthEvent.event == "first_admin_created"))

    assert c.get("/api/setup/state").json()["needs_admin"] is False
    login = c.post("/api/auth/login", json={"username": "jon", "password": "longenoughpw"})
    assert login.status_code == 200 and login.json()["access_token"]


def test_it_closes_after_the_first_admin(make_client, db_session):
    c = make_client()
    assert c.post("/api/setup/admin", json=GOOD).status_code == 201
    r = c.post("/api/setup/admin", json={**GOOD, "username": "intruder"})
    assert r.status_code == 409 and r.json()["detail"] == "setup_done"
    assert db_session.scalar(select(User).where(User.username == "intruder")) is None


def test_any_existing_account_closes_it(make_client, db_session):
    db_session.add(User(username="member1", display_name="M", password_hash="x",
                        role=UserRole.member, is_active=True))
    db_session.commit()
    r = make_client().post("/api/setup/admin", json=GOOD)
    assert r.status_code == 409


def test_a_lan_browser_is_refused(make_client, db_session):
    r = make_client(LAN).post("/api/setup/admin", json=GOOD)
    assert r.status_code == 403 and r.json()["detail"] == "setup_local_only"
    assert db_session.scalar(select(User)) is None


def test_a_tunnel_visitor_is_refused_even_through_loopback(make_client, db_session):
    # cloudflared runs on this PC and reaches the services over loopback, but it
    # passes the visitor's address in CF-Connecting-IP, which wins.
    c = make_client(LOCAL, headers={"cf-connecting-ip": "203.0.113.9"})
    assert c.get("/api/setup/state").json()["local"] is False
    assert c.post("/api/setup/admin", json=GOOD).status_code == 403
    assert db_session.scalar(select(User)) is None


def test_a_lan_browser_cannot_forge_a_loopback_header(make_client, db_session):
    # Forwarded headers count only from a trusted (loopback) peer.
    c = make_client(LAN, headers={"x-forwarded-for": "127.0.0.1"})
    assert c.post("/api/setup/admin", json=GOOD).status_code == 403


@pytest.mark.parametrize("body", [
    {"username": "jon", "password": "short"},
    {"username": "No Spaces", "password": "longenoughpw"},
    {"username": "jo", "password": "longenoughpw"},
])
def test_bad_input_is_rejected(make_client, db_session, body):
    assert make_client().post("/api/setup/admin", json=body).status_code == 422
    assert db_session.scalar(select(User)) is None
