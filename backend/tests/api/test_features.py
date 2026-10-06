"""Optional integrations: /api/client/features and the requests gate."""
from __future__ import annotations

from app.config import settings


def test_features_without_arr(client, monkeypatch):
    monkeypatch.setattr(settings, "radarr_api_key", "")
    monkeypatch.setattr(settings, "sonarr_api_key", "")
    r = client.get("/api/client/features")
    assert r.status_code == 200
    assert r.json()["requests"] == {"enabled": False, "movie": False, "series": False}


def test_features_public_url(client, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://f7five0.tail1234.ts.net/")
    assert client.get("/api/client/features").json()["public_url"] == "https://f7five0.tail1234.ts.net"
    monkeypatch.setattr(settings, "public_url", "")
    assert client.get("/api/client/features").json()["public_url"] is None


def test_features_with_radarr_only(client, monkeypatch):
    monkeypatch.setattr(settings, "radarr_api_key", "k")
    monkeypatch.setattr(settings, "sonarr_api_key", "")
    assert client.get("/api/client/features").json()["requests"] == {
        "enabled": True, "movie": True, "series": False,
    }


def test_requests_disabled_without_arr(client, monkeypatch):
    monkeypatch.setattr(settings, "radarr_api_key", "")
    r = client.post("/api/requests", json={"kind": "movie", "external_id": "603", "title": "The Matrix"})
    assert r.status_code == 409 and r.json()["detail"] == "requests_disabled"
    r = client.get("/api/requests/search", params={"kind": "movie", "q": "matrix"})
    assert r.status_code == 409


def test_base_url_uses_public_scheme_for_public_host(monkeypatch):
    """Tailscale Funnel terminates HTTPS without X-Forwarded-Proto; links on
    the public address must still be https. SEC-P1-1: the forwarded host is
    honoured only from a trusted peer (here loopback) and only if it passes the
    allowlist; an unknown public host is refused and falls back to PUBLIC_URL."""
    from starlette.requests import Request as StarletteRequest

    from app.api.stream import _base_url

    def req(headers):
        # client is loopback -> a trusted proxy peer.
        scope = {
            "type": "http", "scheme": "http", "path": "/",
            "client": ("127.0.0.1", 1234),
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        }
        return StarletteRequest(scope)

    monkeypatch.setattr(settings, "public_url", "https://f7five0.tail1234.ts.net")
    monkeypatch.setattr(settings, "home_url", "")
    assert _base_url(req({"host": "f7five0.tail1234.ts.net"})) == "https://f7five0.tail1234.ts.net"
    # LAN access (a private literal) keeps plain http.
    assert _base_url(req({"host": "192.168.1.20:3001"})) == "http://192.168.1.20:3001"
    # An unknown public host is not in the allowlist, so it is refused and the
    # configured PUBLIC_URL is used instead of the spoofable header.
    assert _base_url(req({"host": "media.example.com", "x-forwarded-proto": "https"})) == "https://f7five0.tail1234.ts.net"
    # A forwarded host from an untrusted peer is ignored entirely.
    untrusted = StarletteRequest({
        "type": "http", "scheme": "http", "path": "/", "client": ("8.8.8.8", 1),
        "headers": [(b"host", b"evil.com"), (b"x-forwarded-proto", b"https")],
    })
    assert _base_url(untrusted) == "https://f7five0.tail1234.ts.net"


def test_features_transcode_hardware(client, monkeypatch):
    monkeypatch.setattr(settings, "nvenc_enabled", False)
    assert client.get("/api/client/features").json()["transcode"] == {"hardware": False}
    monkeypatch.setattr(settings, "nvenc_enabled", True)
    assert client.get("/api/client/features").json()["transcode"] == {"hardware": True}
