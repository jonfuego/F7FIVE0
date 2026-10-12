"""Real concurrency checks for the single-use auth transitions, on PostgreSQL.

SQLite cannot run two requests at once, so these are opt-in. Point
F7FIVE0_PG_TEST_URL at a scratch database whose schema is at head, for example:

    createdb -h 127.0.0.1 -p 55432 -U postgres f7five0_sectest
    cd <repo>; $env:DATABASE_URL = <that url>; alembic upgrade head
    $env:F7FIVE0_PG_TEST_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/f7five0_sectest"
    cd backend; python -m pytest tests/test_pg_concurrency.py -q

NEVER point it at a live database (the tests create and delete their own users,
but they also hammer the sessions table). A database named exactly `f7five0` is
refused.

The "exactly one" tests hold every thread at a barrier after it has read the row
and before it claims it, so all N requests are genuinely in the gap at once. The
free-running test has no barrier and checks the invariants that must hold for
any interleaving.
"""
from __future__ import annotations

import os
import threading
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

PG_URL = os.environ.get("F7FIVE0_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="opt-in: set F7FIVE0_PG_TEST_URL to a scratch PostgreSQL database (see the module docstring)",
)

THREADS = 8
PASSWORD = "concurrency-test-password"


@pytest.fixture(scope="module")
def pg_engine():
    url = make_url(PG_URL)
    assert url.drivername.startswith("postgresql"), "F7FIVE0_PG_TEST_URL must be a PostgreSQL URL"
    if (url.database or "").lower() == "f7five0":
        pytest.fail("refusing to run the concurrency tests against the f7five0 database")
    engine = create_engine(PG_URL, pool_size=THREADS + 4, max_overflow=0, future=True)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("select to_regclass('public.sessions')").scalar() is not None, (
            "the scratch database has no schema: run `alembic upgrade head` against it first"
        )
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_app(pg_engine):
    """The real app, with every request on its own PostgreSQL session."""
    from app.db import get_db
    from app.main import app

    def _db():
        s = Session(pg_engine, expire_on_commit=False, autoflush=False)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def pg_user(pg_engine):
    from app.models.user import User, UserRole
    from app.services.security import hash_password

    with Session(pg_engine, expire_on_commit=False) as s:
        u = User(username=f"conc-{uuid.uuid4().hex[:10]}", display_name="Concurrency",
                 password_hash=hash_password(PASSWORD), role=UserRole.member, is_active=True)
        s.add(u)
        s.commit()
        uid, name = u.id, u.username
    yield types.SimpleNamespace(id=uid, username=name)
    with Session(pg_engine) as s:
        from app.models.user import User as U
        s.query(U).filter(U.id == uid).delete()
        s.commit()


class _client:
    """A TestClient used as a context manager that never runs the app lifespan
    (it starts the scheduler and disposes the engine on exit)."""

    def __init__(self, app):
        from fastapi.testclient import TestClient

        # A real-looking peer: the audit log stores it in an INET column.
        self._c = TestClient(app, client=("203.0.113.5", 50000))

    def __enter__(self):
        return self._c

    def __exit__(self, *exc):
        self._c.close()


def _login(app, user):
    with _client(app) as c:
        r = c.post("/api/auth/login", json={
            "username": user.username, "password": PASSWORD, "client_type": "native",
            "device_name": "Pixel", "platform": "android", "client_version": "1.0.0",
        })
        assert r.status_code == 200, r.text
        return r.json()


def _fire(app, n, make_request):
    """Run `make_request(client)` on n threads at once; return the responses."""
    results: list = [None] * n
    start = threading.Barrier(n)

    def run(i):
        with _client(app) as c:
            start.wait(timeout=30)
            results[i] = make_request(c)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(r is not None for r in results), "a request thread did not finish"
    return results


def _hold_in_the_gap(monkeypatch, module, n):
    """Make every thread wait, once, inside `module._as_utc` (called after the
    handler read the row and before it claims it) until all n threads are there."""
    gap = threading.Barrier(n)
    seen = threading.local()
    real = module._as_utc

    def held(dt):
        if not getattr(seen, "done", False):
            seen.done = True
            gap.wait(timeout=30)
        return real(dt)

    monkeypatch.setattr(module, "_as_utc", held)


def _counts(pg_engine, user):
    from app.models.user import AuthEvent, Session as UserSession

    with Session(pg_engine) as s:
        total = s.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id))
        active = s.scalar(select(func.count()).select_from(UserSession).where(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)))
        events = dict(s.execute(
            select(AuthEvent.event, func.count()).where(AuthEvent.user_id == user.id).group_by(AuthEvent.event)
        ).all())
    return total, active, events


# ---------------------------------------------------------------------------
# Refresh rotation
# ---------------------------------------------------------------------------
def test_concurrent_refresh_exactly_one_rotation(pg_app, pg_engine, pg_user, monkeypatch):
    from app.api import auth as auth_module

    token = _login(pg_app, pg_user)["refresh_token"]
    _hold_in_the_gap(monkeypatch, auth_module, THREADS)
    responses = _fire(pg_app, THREADS, lambda c: c.post("/api/auth/refresh", json={"refresh_token": token}))
    codes = sorted(r.status_code for r in responses)
    assert codes.count(200) == 1, codes
    assert codes.count(401) == THREADS - 1, codes
    total, active, events = _counts(pg_engine, pg_user)
    assert total == 2, "exactly one successor may exist"
    assert events.get("refresh_rotated") == 1
    assert events.get("refresh_reuse_detected") == THREADS - 1
    assert active == 0, "the losers took the reuse path, which revokes every active session"


def test_concurrent_grace_use_exactly_one_success(pg_app, pg_engine, pg_user, monkeypatch):
    from app.api import auth as auth_module

    token = _login(pg_app, pg_user)["refresh_token"]
    with _client(pg_app) as c:  # rotate once, so `token` is now the previous token
        assert c.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 200
    _hold_in_the_gap(monkeypatch, auth_module, THREADS)
    responses = _fire(pg_app, THREADS, lambda c: c.post("/api/auth/refresh", json={"refresh_token": token}))
    codes = sorted(r.status_code for r in responses)
    assert codes.count(200) == 1, codes
    assert codes.count(401) == THREADS - 1, codes
    total, _active, events = _counts(pg_engine, pg_user)
    assert total == 3, "login + one rotation + exactly one grace successor"
    assert events.get("refresh_grace_used") == 1


def test_free_running_refreshes_never_fork_the_chain(pg_app, pg_engine, pg_user):
    """No barrier: whatever the interleaving, there is one rotation, at most one
    grace use, and a session minted per success and no more."""
    token = _login(pg_app, pg_user)["refresh_token"]
    responses = _fire(pg_app, THREADS, lambda c: c.post("/api/auth/refresh", json={"refresh_token": token}))
    ok = sum(1 for r in responses if r.status_code == 200)
    assert 1 <= ok <= 2, [r.status_code for r in responses]
    total, _active, events = _counts(pg_engine, pg_user)
    assert events.get("refresh_rotated") == 1
    assert events.get("refresh_grace_used", 0) <= 1
    assert total == 1 + ok


# ---------------------------------------------------------------------------
# WebAuthn challenge
# ---------------------------------------------------------------------------
def test_concurrent_passkey_verify_exactly_one_session(pg_app, pg_engine, pg_user, monkeypatch):
    import base64
    import json

    from webauthn.helpers import bytes_to_base64url

    from app.api import passkeys as passkeys_module
    from app.config import settings
    from app.models.user import Session as UserSession
    from app.models.webauthn import WebAuthnChallenge, WebAuthnCredential

    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "webauthn_rp_id", "")
    monkeypatch.setattr(settings, "webauthn_origins", "")

    cred_id = bytes_to_base64url(b"conc-cred-" + uuid.uuid4().bytes)
    challenge = bytes_to_base64url(os.urandom(32))
    now = datetime.now(timezone.utc)
    with Session(pg_engine) as s:
        s.add(WebAuthnCredential(
            user_id=pg_user.id, credential_id=cred_id,
            public_key=bytes_to_base64url(b"cose-public-key-bytes-here"), sign_count=0,
            transports="internal", aaguid="00000000-0000-0000-0000-000000000000",
            name="Pixel", created_at=now,
        ))
        s.add(WebAuthnChallenge(
            challenge=challenge, user_id=None, kind="login",
            expires_at=now + timedelta(minutes=5), created_at=now,
        ))
        s.commit()

    monkeypatch.setattr(
        passkeys_module, "verify_authentication_response",
        lambda **kw: types.SimpleNamespace(new_sign_count=1),
    )
    client_data = base64.urlsafe_b64encode(json.dumps({
        "type": "webauthn.get", "challenge": challenge, "origin": "https://media.example.com",
    }).encode()).decode().rstrip("=")
    credential = {
        "id": cred_id, "rawId": cred_id, "type": "public-key",
        "response": {"clientDataJSON": client_data, "authenticatorData": "dummy", "signature": "dummy"},
    }
    _hold_in_the_gap(monkeypatch, passkeys_module, THREADS)
    try:
        responses = _fire(pg_app, THREADS, lambda c: c.post(
            "/api/auth/passkey/login/verify", json={"credential": credential}))
        codes = sorted(r.status_code for r in responses)
        assert codes.count(200) == 1, codes
        assert codes.count(400) == THREADS - 1, codes
        assert {r.json()["detail"] for r in responses if r.status_code == 400} == {"challenge_already_used"}
        with Session(pg_engine) as s:
            minted = s.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == pg_user.id))
            consumed = s.scalar(select(WebAuthnChallenge.consumed_at).where(WebAuthnChallenge.challenge == challenge))
        assert minted == 1, "exactly one session may be issued for one assertion"
        assert consumed is not None
    finally:
        with Session(pg_engine) as s:
            s.query(WebAuthnChallenge).filter(WebAuthnChallenge.challenge == challenge).delete()
            s.query(WebAuthnCredential).filter(WebAuthnCredential.credential_id == cred_id).delete()
            s.commit()
