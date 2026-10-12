"""Progress, the played rule and the show page: per user."""
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


def test_show_page_lists_episodes_newest_first_with_the_callers_state(api, db_session):
    a, b = make_user(db_session), make_user(db_session)
    pod = make_podcast(db_session)
    old = make_episode(db_session, pod, title="Old", published=datetime(2024, 1, 1, tzinfo=timezone.utc))
    new = make_episode(db_session, pod, title="New", published=datetime(2025, 1, 1, tzinfo=timezone.utc))
    subscribe(db_session, a, pod)
    api.as_user(a).put(f"/api/podcasts/episodes/{new.id}/progress", json={"position_sec": 120, "duration_sec": 3600})
    body = api.as_user(a).get(f"/api/podcasts/{pod.id}").json()
    assert [e["title"] for e in body["episodes"]] == ["New", "Old"]
    states = {e["title"]: e["state"] for e in body["episodes"]}
    assert states == {"New": {"kind": "in_progress", "position_sec": 120}, "Old": {"kind": "new"}}
    # B sees neither A's subscription nor A's progress.
    body_b = api.as_user(b).get(f"/api/podcasts/{pod.id}").json()
    assert body_b["podcast"]["subscribed"] is False
    assert {e["title"]: e["state"]["kind"] for e in body_b["episodes"]} == {"New": "new", "Old": "new"}
    assert old.id != new.id


# ---------------------------------------------------------------------------
# Progress and played
# ---------------------------------------------------------------------------
def test_progress_is_saved_per_user_and_resumes(api, db_session):
    a, b = make_user(db_session), make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=3600)
    r = api.as_user(a).put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": 300, "duration_sec": 3600})
    assert r.status_code == 200 and r.json()["state"] == {"kind": "in_progress", "position_sec": 300}
    row = db_session.get(PodcastEpisodeProgress, (a.id, ep.id))
    assert row.position_sec == 300 and row.duration_sec == 3600
    assert db_session.get(PodcastEpisodeProgress, (b.id, ep.id)) is None
    # Home: A has it under In progress, B does not.
    assert [e["id"] for e in api.as_user(a).get("/api/podcasts").json()["in_progress"]] == [str(ep.id)]
    assert api.as_user(b).get("/api/podcasts").json()["in_progress"] == []


@pytest.mark.parametrize(
    "position, duration, played",
    [
        (6839, 7200, False),   # long show: 95% (6840) comes before the last 30 s (7170)
        (6840, 7200, True),
        (269, 300, False),     # short show: the last 30 s (270) come before 95% (285)
        (270, 300, True),
        (569, 600, False),     # both rules land on 570
        (570, 600, True),
        (3419, 3600, False),
        (3420, 3600, True),
    ],
)
def test_played_when_within_30s_of_the_end_or_past_95_percent(api, db_session, position, duration, played):
    u = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session), duration=duration)
    r = api.as_user(u).put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": position, "duration_sec": duration})
    assert r.status_code == 200
    assert (r.json()["state"]["kind"] == "played") is played


def test_manual_played_and_unplayed(api, db_session):
    u = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    c = api.as_user(u)
    assert c.post(f"/api/podcasts/episodes/{ep.id}/played").json()["state"] == {"kind": "played"}
    assert c.delete(f"/api/podcasts/episodes/{ep.id}/played").json()["state"] == {"kind": "new"}
    c.put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": 90, "duration_sec": 3600})
    assert c.post(f"/api/podcasts/episodes/{ep.id}/played").json()["state"]["kind"] == "played"
    r = c.delete(f"/api/podcasts/episodes/{ep.id}/played")
    assert r.json()["state"] == {"kind": "new"}
    row = db_session.get(PodcastEpisodeProgress, (u.id, ep.id))
    assert row.position_sec == 0


def test_listening_again_after_played_goes_back_to_in_progress(api, db_session):
    u = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session), duration=3600)
    c = api.as_user(u)
    assert c.put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": 3590, "duration_sec": 3600}).json()["state"]["kind"] == "played"
    assert c.put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": 40, "duration_sec": 3600}).json()["state"] == {"kind": "in_progress", "position_sec": 40}


def test_progress_validation(api, db_session):
    u = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    c = api.as_user(u)
    assert c.put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": -5, "duration_sec": 10}).status_code == 422
    assert c.put(f"/api/podcasts/episodes/{uuid.uuid4()}/progress", json={"position_sec": 5, "duration_sec": 10}).status_code == 404


def test_speed_is_a_per_user_view_pref(api, db_session):
    from app.api import view_prefs
    assert view_prefs.KEY_RE.match("podcast_speed")
    from app.services import longform
    assert longform.clamp_speed(0.1) == 0.5 and longform.clamp_speed(9) == 3.0 and longform.clamp_speed(1.25) == 1.25
    u = make_user(db_session)
    r = api.as_user(u).put("/api/view-prefs/podcast_speed", json={"value": 1.5})
    assert r.status_code == 200 and r.json()["value"] == 1.5
    for bad in (0.4, 3.1, "fast", True):
        assert api.as_user(u).put("/api/view-prefs/podcast_speed", json={"value": bad}).status_code == 422
    assert api.as_user(make_user(db_session)).get("/api/view-prefs").json()["prefs"].get("podcast_speed") is None


