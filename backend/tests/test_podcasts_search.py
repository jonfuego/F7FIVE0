"""Directory search (Podcast Index when a key is set, iTunes when not) and the
Podcast Index key (Admin-saved wins over .env, secret never returned, never
logged)."""
from __future__ import annotations

import hashlib
import logging

import httpx
import pytest

from app.config import settings
from app.services import podcastindex_key
from app.services.podcasts import search as search_service
from tests.podcast_helpers import Api, install_dns, install_transport, make_user

KEY, SECRET = "PIKEYABCDEF", "pi-secret-do-not-leak-0123456789"

PI_BODY = {"status": "true", "feeds": [
    {"title": "PI Show", "author": "PI Author", "image": "https://img.example/pi.jpg",
     "artwork": "https://img.example/pi-art.jpg", "url": "https://pi.example/feed.xml"},
    {"title": "Second", "author": "", "image": "", "artwork": "", "url": "https://pi.example/two.xml"},
]}
ITUNES_BODY = {"resultCount": 2, "results": [
    {"collectionName": "iTunes Show", "artistName": "Apple Author", "artworkUrl600": "https://img.example/it.jpg",
     "feedUrl": "https://it.example/rss"},
    {"collectionName": "No feed", "artistName": "x", "artworkUrl600": "https://img.example/x.jpg"},
]}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    install_dns(monkeypatch)
    monkeypatch.setattr(settings, "podcastindex_api_key", "")
    monkeypatch.setattr(settings, "podcastindex_api_secret", "")
    podcastindex_key.reset_cache()
    yield
    podcastindex_key.reset_cache()


@pytest.fixture()
def api(db_session):
    a = Api(db_session)
    yield a
    a.close()


def _search_handler(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.podcastindex.org":
            return httpx.Response(200, json=PI_BODY)
        if request.url.host == "itunes.apple.com":
            return httpx.Response(200, content=__import__("json").dumps(ITUNES_BODY).encode(), headers={"content-type": "text/javascript; charset=utf-8"})
        return httpx.Response(404)
    return handler


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def test_without_a_key_search_uses_itunes(api, db_session, monkeypatch):
    seen: list = []
    install_transport(monkeypatch, _search_handler(seen))
    u = make_user(db_session)
    r = api.as_user(u).get("/api/podcasts/search", params={"q": "the daily"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "itunes"
    assert body["results"] == [{
        "title": "iTunes Show", "author": "Apple Author", "art_url": "https://img.example/it.jpg",
        "feed_url": "https://it.example/rss", "provider": "itunes",
    }]
    req = seen[0]
    assert req.url.host == "itunes.apple.com" and req.url.params["media"] == "podcast"
    assert req.url.params["term"] == "the daily"


def test_with_a_key_search_uses_podcast_index_signed_per_its_docs(api, db_session, monkeypatch):
    seen: list = []
    install_transport(monkeypatch, _search_handler(seen))
    podcastindex_key.save(db_session, KEY, SECRET)
    u = make_user(db_session)
    r = api.as_user(u).get("/api/podcasts/search", params={"q": "linux"})
    assert r.status_code == 200 and r.json()["provider"] == "podcastindex"
    results = r.json()["results"]
    assert results[0] == {"title": "PI Show", "author": "PI Author", "art_url": "https://img.example/pi.jpg",
                          "feed_url": "https://pi.example/feed.xml", "provider": "podcastindex"}
    req = seen[0]
    assert req.url.host == "api.podcastindex.org" and req.url.path == "/api/1.0/search/byterm"
    assert req.url.params["q"] == "linux"
    h = req.headers
    assert h["x-auth-key"] == KEY
    date = h["x-auth-date"]
    assert date.isdigit()
    assert h["authorization"] == hashlib.sha1((KEY + SECRET + date).encode()).hexdigest()
    assert h["user-agent"].startswith("F7FIVE0/")


def test_env_key_works_and_the_admin_saved_key_wins(db_session, monkeypatch):
    monkeypatch.setattr(settings, "podcastindex_api_key", "ENVKEY")
    monkeypatch.setattr(settings, "podcastindex_api_secret", "ENVSECRET")
    assert podcastindex_key.get() == ("ENVKEY", "ENVSECRET")
    assert podcastindex_key.source(db_session) == "env"
    podcastindex_key.save(db_session, KEY, SECRET)
    assert podcastindex_key.get() == (KEY, SECRET)
    assert podcastindex_key.source(db_session) == "admin"
    podcastindex_key.clear(db_session)
    assert podcastindex_key.get() == ("ENVKEY", "ENVSECRET")


def test_a_key_without_a_secret_counts_as_no_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "podcastindex_api_key", "ENVKEY")
    assert podcastindex_key.get() == ("", "")
    assert search_service.provider_name() == "itunes"


def test_search_failure_is_a_502_not_a_crash(api, db_session, monkeypatch):
    install_transport(monkeypatch, lambda r: httpx.Response(500))
    u = make_user(db_session)
    r = api.as_user(u).get("/api/podcasts/search", params={"q": "x"})
    assert r.status_code == 502 and r.json()["detail"] == "search_failed"
    assert api.as_user(u).get("/api/podcasts/search", params={"q": ""}).status_code == 422


# ---------------------------------------------------------------------------
# The key in Admin
# ---------------------------------------------------------------------------
def test_admin_key_endpoints_never_return_the_secret(api, db_session, monkeypatch):
    seen: list = []
    install_transport(monkeypatch, _search_handler(seen))
    admin = make_user(db_session, role="admin")
    c = api.as_user(admin)
    r = c.get("/api/admin/metadata")
    assert r.json()["podcastindex"] == {"configured": False, "source": None, "key_masked": None, "secret_set": False}

    r = c.put("/api/admin/metadata/podcastindex", json={"key": KEY, "secret": SECRET})
    assert r.status_code == 200, r.text
    pi = r.json()["podcastindex"]
    assert pi["configured"] is True and pi["source"] == "admin" and pi["secret_set"] is True
    assert pi["key_masked"].endswith(KEY[-4:])
    for text in (r.text, c.get("/api/admin/metadata").text):
        assert SECRET not in text and "secret\":" not in text.replace("secret_set", "")
    assert "secret" not in pi or pi.get("secret") is None
    assert podcastindex_key.get() == (KEY, SECRET)

    r = c.delete("/api/admin/metadata/podcastindex")
    assert r.status_code == 200 and r.json()["podcastindex"]["configured"] is False


def test_admin_test_button_runs_one_search_and_a_bad_key_is_not_saved(api, db_session, monkeypatch):
    seen: list = []
    install_transport(monkeypatch, _search_handler(seen))
    admin = make_user(db_session, role="admin")
    c = api.as_user(admin)
    r = c.post("/api/admin/metadata/podcastindex/test", json={"key": KEY, "secret": SECRET})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(seen) == 1 and seen[0].url.host == "api.podcastindex.org"
    assert podcastindex_key.get() == ("", ""), "testing does not save"

    install_transport(monkeypatch, lambda req: httpx.Response(401, json={"status": "false"}))
    r = c.put("/api/admin/metadata/podcastindex", json={"key": "bad", "secret": "bad"})
    assert r.status_code == 400
    assert podcastindex_key.get() == ("", "")
    r = c.post("/api/admin/metadata/podcastindex/test", json={"key": "bad", "secret": "bad"})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_no_key_secret_or_authorization_value_reaches_the_logs(api, db_session, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    seen: list = []
    install_transport(monkeypatch, _search_handler(seen))
    admin = make_user(db_session, role="admin")
    c = api.as_user(admin)
    c.put("/api/admin/metadata/podcastindex", json={"key": KEY, "secret": SECRET})
    c.get("/api/podcasts/search", params={"q": "linux"})
    install_transport(monkeypatch, lambda req: httpx.Response(500, json={"description": "nope"}))
    c.get("/api/podcasts/search", params={"q": "linux"})
    c.post("/api/admin/metadata/podcastindex/test", json={"key": KEY, "secret": SECRET})
    auth = [r.headers["authorization"] for r in seen if "authorization" in r.headers]
    assert auth, "the signed request was made"
    text = caplog.text
    assert SECRET not in text and KEY not in text
    for value in auth:
        assert value not in text
