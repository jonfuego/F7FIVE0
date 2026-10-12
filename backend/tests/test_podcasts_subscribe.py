"""Subscribe, unsubscribe, auto-download and OPML: per user."""
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
# Subscribe, unsubscribe, per user
# ---------------------------------------------------------------------------
def test_subscribe_fetches_the_feed_and_is_per_user(api, db_session, monkeypatch):
    install_transport(monkeypatch, _feed_ok)
    a, b = make_user(db_session), make_user(db_session)

    r = api.as_user(a).post("/api/podcasts/subscribe", json={"feed_url": FEED_A})
    assert r.status_code == 200, r.text
    show = r.json()
    assert show["title"] == "The Fixture Show" and show["subscribed"] is True
    assert show["episode_count"] == 3
    assert db_session.scalar(select(func.count()).select_from(PodcastEpisode)) == 3

    mine_a = api.as_user(a).get("/api/podcasts").json()
    assert [p["id"] for p in mine_a["mine"]] == [show["id"]]
    mine_b = api.as_user(b).get("/api/podcasts").json()
    assert mine_b["mine"] == []

    # B subscribes to the same feed: no second show, no second fetch of episodes.
    r = api.as_user(b).post("/api/podcasts/subscribe", json={"feed_url": FEED_A})
    assert r.status_code == 200 and r.json()["id"] == show["id"]
    assert db_session.scalar(select(func.count()).select_from(Podcast)) == 1
    assert db_session.scalar(select(func.count()).select_from(PodcastSubscription)) == 2

    # A unsubscribes; B is untouched.
    assert api.as_user(a).delete(f"/api/podcasts/{show['id']}/subscription").status_code == 204
    assert api.as_user(a).get("/api/podcasts").json()["mine"] == []
    assert [p["id"] for p in api.as_user(b).get("/api/podcasts").json()["mine"]] == [show["id"]]


def test_subscribe_to_a_dead_feed_reports_it_and_creates_nothing(api, db_session, monkeypatch):
    install_transport(monkeypatch, lambda r: httpx.Response(404))
    u = make_user(db_session)
    r = api.as_user(u).post("/api/podcasts/subscribe", json={"feed_url": FEED_A})
    assert r.status_code == 502 and r.json()["detail"] == "feed_unreachable"
    assert db_session.scalar(select(func.count()).select_from(Podcast)) == 0


def test_subscribe_rejects_a_private_url_and_bad_input(api, db_session, monkeypatch):
    calls = install_transport(monkeypatch, _feed_ok)
    u = make_user(db_session)
    c = api.as_user(u)
    assert c.post("/api/podcasts/subscribe", json={"feed_url": "http://127.0.0.1/feed"}).status_code in (400, 502)
    assert c.post("/api/podcasts/subscribe", json={"feed_url": "ftp://x.example/feed"}).status_code == 422
    assert c.post("/api/podcasts/subscribe", json={}).status_code == 422
    assert len(calls) == 0


def test_subscribe_a_local_show_by_id(api, db_session):
    u = make_user(db_session)
    pod = make_podcast(db_session, title="Local Only", feed_url=None, source="local")
    r = api.as_user(u).post("/api/podcasts/subscribe", json={"podcast_id": str(pod.id)})
    assert r.status_code == 200 and r.json()["subscribed"] is True


def test_auto_download_toggle_needs_a_subscription(api, db_session):
    a, b = make_user(db_session), make_user(db_session)
    pod = make_podcast(db_session)
    subscribe(db_session, a, pod)
    assert api.as_user(b).patch(f"/api/podcasts/{pod.id}/subscription", json={"auto_download": True}).status_code == 404
    r = api.as_user(a).patch(f"/api/podcasts/{pod.id}/subscription", json={"auto_download": True})
    assert r.status_code == 200 and r.json()["auto_download"] is True
    sub = db_session.get(PodcastSubscription, (a.id, pod.id))
    assert sub.auto_download is True
    # B's view of the same show is untouched.
    assert api.as_user(b).delete(f"/api/podcasts/{pod.id}/subscription").status_code == 404


# ---------------------------------------------------------------------------
# OPML
# ---------------------------------------------------------------------------
def test_opml_import_counts_and_fetches_new_shows_in_the_background(api, db_session, monkeypatch):
    queued: list = []
    monkeypatch.setattr(scheduler, "trigger_podcast_refresh_now", lambda ids=None: queued.append(list(ids or [])))
    calls = install_transport(monkeypatch, _feed_ok)
    u = make_user(db_session)
    existing = make_podcast(db_session, title="Alpha", feed_url="https://alpha.example/feed.xml")
    subscribe(db_session, u, existing)
    r = api.as_user(u).post("/api/podcasts/opml", files={"file": ("subs.opml", fixture_bytes("opml_in.xml"), "text/x-opml")})
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 2, "already": 1, "failed": 1}
    assert len(calls) == 0, "new shows are fetched in the background, not in the request"
    assert len(queued) == 1 and len(queued[0]) == 2
    assert db_session.scalar(select(func.count()).select_from(PodcastSubscription)) == 3


def test_opml_export_then_import_round_trip(api, db_session, monkeypatch):
    a, b = make_user(db_session), make_user(db_session)
    for host in ("one", "two"):
        subscribe(db_session, a, make_podcast(db_session, title=f"Show {host}", feed_url=f"https://{host}.example/rss"))
    subscribe(db_session, a, make_podcast(db_session, title="Local", feed_url=None, source="local"))
    r = api.as_user(a).get("/api/podcasts/opml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    text = r.text
    assert 'version="2.0"' in text and "https://one.example/rss" in text and "https://two.example/rss" in text
    assert "Local" not in text

    out = api.as_user(b).post("/api/podcasts/opml", files={"file": ("subs.opml", r.content, "text/x-opml")})
    assert out.json() == {"added": 2, "already": 0, "failed": 0}
    assert api.as_user(b).post("/api/podcasts/opml", files={"file": ("subs.opml", r.content, "text/x-opml")}).json() == {"added": 0, "already": 2, "failed": 0}


def test_opml_upload_over_1mb_is_refused(api, db_session):
    u = make_user(db_session)
    big = b"<opml version='2.0'><body>" + b"<outline text='x'/>" * 70000 + b"</body></opml>"
    assert len(big) > net_guard.OPML_MAX_BYTES
    r = api.as_user(u).post("/api/podcasts/opml", files={"file": ("big.opml", big, "text/x-opml")})
    assert r.status_code == 413


def test_opml_with_entity_expansion_is_refused(api, db_session):
    u = make_user(db_session)
    r = api.as_user(u).post("/api/podcasts/opml", files={"file": ("bad.opml", fixture_bytes("billion_laughs.xml"), "text/x-opml")})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_opml"
    r = api.as_user(u).post("/api/podcasts/opml", files={"file": ("bad.opml", b"not xml at all", "text/x-opml")})
    assert r.status_code == 400


