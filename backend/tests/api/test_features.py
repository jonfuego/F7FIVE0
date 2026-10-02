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
    the public address must still be https."""
    from starlette.requests import Request as StarletteRequest

    from app.api.stream import _base_url

    def req(headers):
        scope = {"type": "http", "scheme": "http", "path": "/", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
        return StarletteRequest(scope)

    monkeypatch.setattr(settings, "public_url", "https://f7five0.tail1234.ts.net")
    assert _base_url(req({"host": "f7five0.tail1234.ts.net"})) == "https://f7five0.tail1234.ts.net"
    # LAN access keeps plain http.
    assert _base_url(req({"host": "192.168.1.20:3001"})) == "http://192.168.1.20:3001"
    # An explicit forwarded proto on other hosts is still honored.
    assert _base_url(req({"host": "media.example.com", "x-forwarded-proto": "https"})) == "https://media.example.com"


def test_features_transcode_hardware(client, monkeypatch):
    monkeypatch.setattr(settings, "nvenc_enabled", False)
    assert client.get("/api/client/features").json()["transcode"] == {"hardware": False}
    monkeypatch.setattr(settings, "nvenc_enabled", True)
    assert client.get("/api/client/features").json()["transcode"] == {"hardware": True}
