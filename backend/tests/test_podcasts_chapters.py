"""Chapters: the feed JSON, the server file, nothing; cached and safe."""
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
from app.services.podcasts import chapters as chapters_service
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
# Chapters
# ---------------------------------------------------------------------------
def test_chapters_from_the_feed_json_are_normalised_cached_and_safe(api, db_session, monkeypatch):
    calls = install_transport(monkeypatch, lambda r: httpx.Response(200, content=fixture_bytes("chapters.json"), headers={"content-type": "application/json+chapters"}))
    u = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    ep.chapters_url = "https://fixture.example/ep3.chapters.json"
    db_session.commit()
    r = api.as_user(u).get(f"/api/podcasts/episodes/{ep.id}/chapters")
    assert r.status_code == 200
    chapters = r.json()
    assert [c["title"] for c in chapters] == ["Intro", "Main topic", "Evil link"]
    assert chapters[1] == {"start_sec": 125.5, "title": "Main topic", "img": "https://fixture.example/c2.jpg", "url": "https://fixture.example/c2"}
    assert chapters[2] == {"start_sec": 1500.0, "title": "Evil link"}
    assert chapters[0] == {"start_sec": 0.0, "title": "Intro"}
    assert len(calls) == 1
    api.as_user(u).get(f"/api/podcasts/episodes/{ep.id}/chapters")
    assert len(calls) == 1, "the second request is served from chapters_json"
    assert db_session.get(PodcastEpisode, ep.id).chapters_json


def test_chapters_url_to_a_private_host_is_rejected_and_never_fetched(api, db_session, monkeypatch):
    calls = install_transport(monkeypatch, lambda r: httpx.Response(200, json={"chapters": []}))
    u = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    ep.chapters_url = "http://10.0.0.5/chapters.json"
    db_session.commit()
    assert api.as_user(u).get(f"/api/podcasts/episodes/{ep.id}/chapters").json() == []
    assert chapters_service.get_chapters(db_session, ep) == []
    assert len(calls) == 0


def test_chapters_fall_back_to_the_server_file_then_to_nothing(api, db_session, monkeypatch, tmp_path):
    from app.models.media_file import MediaFile, MediaKind, ScanState
    u = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod)
    assert api.as_user(u).get(f"/api/podcasts/episodes/{ep.id}/chapters").json() == []

    f = tmp_path / "ep.mp3"
    f.write_bytes(b"x")
    mf = MediaFile(kind=MediaKind.podcast_episode, ref_id=ep.id, path=str(f), scan_state=ScanState.ready)
    db_session.add(mf)
    db_session.flush()
    ep.media_file_id = mf.id
    monkeypatch.setattr(ffprobe, "probe_chapters", lambda path, timeout=30.0: [{"start_sec": 0.0, "title": "From file"}, {"start_sec": 60.0, "title": "Two"}])
    assert [c["title"] for c in api.as_user(u).get(f"/api/podcasts/episodes/{ep.id}/chapters").json()] == ["From file", "Two"]


