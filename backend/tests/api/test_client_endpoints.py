"""Client-support endpoints: /api/client/min-version (no auth) and
/api/client/errors (auth, 8 KB cap, one log line)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import current_user, get_db
from app.config import settings
from app.main import app
from app.models.user import User
from app.services.security import hash_password


@pytest.fixture()
def user(db_session):
    u = User(
        username="client-user", display_name="Client User",
        password_hash=hash_password("x-strong-pass"), role="member", is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def api(db_session, user):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = lambda: user
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_min_version_requires_no_auth_and_returns_all_platforms(db_session):
    # No dependency overrides for auth: the route must be reachable without a
    # token. Only get_db is overridden so nothing touches a real Postgres.
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        client = TestClient(app)
        resp = client.get("/api/client/min-version")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"android", "ios", "android_tv", "tvos"}
        assert body["android"] == settings.min_client_version_android
        client.close()
    finally:
        app.dependency_overrides.clear()


def test_error_report_accepted_and_capped(api):
    ok = api.post(
        "/api/client/errors",
        json={
            "message": "TypeError: undefined is not a function",
            "stack": "at Foo (bar.tsx:12)",
            "platform": "android",
            "client_version": "1.0.0",
            "fatal": True,
            "context": "now-playing",
        },
    )
    assert ok.status_code == 204, ok.text


def test_error_report_over_8kb_rejected(api):
    huge = api.post(
        "/api/client/errors",
        json={"message": "x", "stack": "A" * (9 * 1024)},
    )
    assert huge.status_code == 413


def test_error_report_invalid_body_rejected(api):
    bad = api.post(
        "/api/client/errors",
        content=b"not json at all",
        headers={"content-type": "application/json"},
    )
    assert bad.status_code == 422
