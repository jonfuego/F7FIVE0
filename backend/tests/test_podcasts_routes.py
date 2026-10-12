"""Every podcast route needs a signed-in user; admin routes need an admin."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app import scheduler
from app.models.podcast import (
    Podcast, PodcastEpisode, PodcastEpisodeProgress, PodcastSubscription,
)
from app.services import ffprobe, net_guard
from app.services.podcasts import refresh
from tests.podcast_helpers import (
    Api, fixture_bytes, install_dns, install_transport, make_episode, make_podcast,
    make_user, subscribe,
)

FEED_A = "https://alpha.example/feed.xml"


@pytest.fixture(autouse=True)
def _net(monkeypatch):
    install_dns(monkeypatch)
    monkeypatch.setattr(refresh, "sync_art", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "trigger_podcast_refresh_now", lambda *a, **k: None)


@pytest.fixture()
def api(db_session):
    a = Api(db_session)
    yield a
    a.close()


def _feed_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=fixture_bytes("feed.xml"), headers={"etag": '"e1"'})


# ---------------------------------------------------------------------------
# Auth on every route
# ---------------------------------------------------------------------------
def _podcast_routes():
    """(METHOD, path) for every podcast route, read from the OpenAPI document
    (FastAPI keeps included routers lazy, so app.routes does not list them)."""
    from app.main import app
    out = []
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api/podcasts") or path.startswith("/api/admin/podcasts"):
            for method in operations:
                if method in ("get", "post", "put", "patch", "delete"):
                    out.append((method.upper(), path))
    return sorted(out)


def _fill(path: str) -> str:
    return path.replace("{id}", str(uuid.uuid4())).replace("{podcast_id}", str(uuid.uuid4())).replace("{episode_id}", str(uuid.uuid4()))


def test_every_podcast_route_exists_and_rejects_an_anonymous_caller(api):
    routes = _podcast_routes()
    expected = {
        ("GET", "/api/podcasts/search"), ("POST", "/api/podcasts/subscribe"),
        ("PATCH", "/api/podcasts/{id}/subscription"), ("DELETE", "/api/podcasts/{id}/subscription"),
        ("GET", "/api/podcasts/opml"), ("POST", "/api/podcasts/opml"),
        ("PUT", "/api/podcasts/episodes/{id}/progress"),
        ("POST", "/api/podcasts/episodes/{id}/played"), ("DELETE", "/api/podcasts/episodes/{id}/played"),
        ("GET", "/api/podcasts/episodes/{id}/chapters"), ("POST", "/api/podcasts/episodes/{id}/download"),
        ("DELETE", "/api/admin/podcasts/episodes/{id}/download"),
    }
    assert expected <= set(routes), expected - set(routes)
    c = api.anonymous()
    for method, path in routes:
        r = c.request(method, _fill(path), json={})
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_every_admin_podcast_route_rejects_a_member(api, db_session):
    member = make_user(db_session, role="member")
    c = api.as_user(member)
    admin_routes = [(m, p) for m, p in _podcast_routes() if p.startswith("/api/admin/")]
    assert admin_routes
    for method, path in admin_routes:
        r = c.request(method, _fill(path), json={})
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
