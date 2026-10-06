"""SEC-P1-1: forwarded headers are honoured only from a trusted proxy peer.

Covers the helper (peer trust, real client IP, host allowlist, forwarded
origin) and the two end-to-end guarantees the spec asks for: a spoofed
CF-Connecting-IP from an untrusted peer does not drive the audit IP or the
login throttle, and a spoofed X-Forwarded-Host from an untrusted peer never
lands in a signed stream URL.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import settings
from app.db import get_db
from app.main import app
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.user import User, UserRole
from app.services import trusted_proxy
from app.services.security import hash_password
from app.services.trusted_proxy import (
    forwarded_origin,
    host_is_allowed,
    peer_is_trusted,
    real_client_ip,
)


def _request(peer, headers, scheme="http"):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw,
        "scheme": scheme,
        "server": ("127.0.0.1", 8001),
        "client": (peer, 12345) if peer else None,
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# peer_is_trusted
# ---------------------------------------------------------------------------
def test_loopback_peer_is_trusted():
    assert peer_is_trusted("127.0.0.1") is True
    assert peer_is_trusted("::1") is True


def test_lan_peer_is_not_trusted_by_default():
    assert peer_is_trusted("192.168.1.50") is False
    assert peer_is_trusted("10.0.0.9") is False


def test_configured_cidr_is_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.8.0.0/24")
    assert peer_is_trusted("10.8.0.3") is True
    assert peer_is_trusted("10.9.0.3") is False


def test_garbage_peer_is_not_trusted():
    assert peer_is_trusted("testclient") is False
    assert peer_is_trusted(None) is False


# ---------------------------------------------------------------------------
# real_client_ip
# ---------------------------------------------------------------------------
def test_trusted_peer_header_is_honoured():
    req = _request("127.0.0.1", {"cf-connecting-ip": "203.0.113.7"})
    assert real_client_ip(req) == "203.0.113.7"


def test_trusted_peer_xff_first_hop():
    req = _request("127.0.0.1", {"x-forwarded-for": "203.0.113.7, 10.0.0.1"})
    assert real_client_ip(req) == "203.0.113.7"


def test_untrusted_peer_header_ignored():
    req = _request("192.168.1.50", {"cf-connecting-ip": "203.0.113.7"})
    assert real_client_ip(req) == "192.168.1.50"


# ---------------------------------------------------------------------------
# host_is_allowed
# ---------------------------------------------------------------------------
def test_configured_public_host_allowed(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "home_url", "")
    assert host_is_allowed("media.example.com") is True
    assert host_is_allowed("media.example.com:443") is True


def test_private_and_loopback_hosts_allowed():
    assert host_is_allowed("192.168.1.20:3101") is True
    assert host_is_allowed("127.0.0.1:8002") is True
    assert host_is_allowed("localhost") is True


def test_unknown_public_host_rejected(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "home_url", "")
    assert host_is_allowed("evil.com") is False


def test_injected_host_rejected():
    assert host_is_allowed("evil.com\r\nSet-Cookie: x=1") is False
    assert host_is_allowed("evil.com, media.example.com") is False
    assert host_is_allowed("") is False


# ---------------------------------------------------------------------------
# forwarded_origin
# ---------------------------------------------------------------------------
def test_forwarded_origin_from_trusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "home_url", "")
    req = _request("127.0.0.1", {
        "x-forwarded-host": "media.example.com",
        "x-forwarded-proto": "https",
    })
    assert forwarded_origin(req) == ("media.example.com", "https")


def test_forwarded_origin_ignored_from_untrusted_peer():
    req = _request("192.168.1.50", {
        "x-forwarded-host": "evil.com",
        "x-forwarded-proto": "https",
    })
    assert forwarded_origin(req) == (None, None)


def test_forwarded_origin_rejects_disallowed_host_even_from_trusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "home_url", "")
    req = _request("127.0.0.1", {"x-forwarded-host": "evil.com"})
    assert forwarded_origin(req) == (None, None)


# ---------------------------------------------------------------------------
# End-to-end: untrusted spoof ignored for audit IP, login throttle, signed URL
# ---------------------------------------------------------------------------
@pytest.fixture()
def api(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    # The in-memory throttle is module-global; start clean so prior tests in
    # the session don't leak failure counts into these.
    from app.api import auth as auth_module
    auth_module._login_failures.clear()
    client = TestClient(app)
    try:
        yield client, db_session
    finally:
        client.close()
        app.dependency_overrides.clear()
        auth_module._login_failures.clear()


def _make_user(db):
    user = User(
        username="proxy-user",
        display_name="Proxy User",
        password_hash=hash_password("hunter2password"),
        role=UserRole.member,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_spoofed_cf_ip_not_recorded_in_audit(api):
    client, db = api
    _make_user(db)
    # Wrong password -> login_failed event. The TestClient peer ("testclient")
    # is untrusted, so the spoofed CF-Connecting-IP must not become the audit IP.
    resp = client.post(
        "/api/auth/login",
        json={"username": "proxy-user", "password": "wrong"},
        headers={"cf-connecting-ip": "9.9.9.9"},
    )
    assert resp.status_code == 401
    from app.models.user import AuthEvent
    events = db.query(AuthEvent).all()
    assert events, "expected an auth event"
    assert all(e.ip != "9.9.9.9" for e in events)


def test_login_throttle_ignores_spoofed_ip(api):
    client, db = api
    _make_user(db)
    # Five failures, each with a DIFFERENT spoofed CF-Connecting-IP but the
    # same real (untrusted) peer. If the throttle keyed on the spoofed header,
    # each would get its own counter and the sixth would never trip. It trips,
    # proving the spoofed IP is ignored.
    for i in range(5):
        r = client.post(
            "/api/auth/login",
            json={"username": "proxy-user", "password": "wrong"},
            headers={"cf-connecting-ip": f"9.9.9.{i}"},
        )
        assert r.status_code == 401, r.text
    blocked = client.post(
        "/api/auth/login",
        json={"username": "proxy-user", "password": "wrong"},
        headers={"cf-connecting-ip": "9.9.9.99"},
    )
    assert blocked.status_code == 429


def test_spoofed_forwarded_host_not_in_signed_url(api):
    client, db = api
    user = _make_user(db)

    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=uuid.uuid4(),
        path=r"C:\Media\Movies\a.mp4",
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1920,
        height=1080,
        size_bytes=16,
        duration_sec=120,
        scan_state=ScanState.ready,
    )
    db.add(mf)
    db.commit()

    # Authenticate as this user via dependency overrides on current_user and
    # current_session_id (stream/start binds the signed URL to the session).
    from app.api.deps import current_session_id as sid_dep
    from app.api.deps import current_user as current_user_dep
    from tests.conftest import make_active_session
    sess = make_active_session(db, user=user)[1]
    app.dependency_overrides[current_user_dep] = lambda: user
    app.dependency_overrides[sid_dep] = lambda: sess.id
    try:
        resp = client.post(
            "/api/stream/start",
            json={"file_id": str(mf.id)},
            headers={"x-forwarded-host": "evil.com", "x-forwarded-proto": "https"},
        )
    finally:
        app.dependency_overrides.pop(current_user_dep, None)
        app.dependency_overrides.pop(sid_dep, None)

    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    assert "evil.com" not in url
    assert url.startswith("http://127.0.0.1:")
