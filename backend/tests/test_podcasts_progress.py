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




# ---------------------------------------------------------------------------
# Late saves never move the place back
# ---------------------------------------------------------------------------
def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_a_save_taken_before_the_stored_one_is_ignored(api, db_session, caplog):
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=7200)
    now = datetime.now(timezone.utc)
    url = f"/api/podcasts/episodes/{ep.id}/progress"
    r = api.as_user(a).put(url, json={"position_sec": 2400, "recorded_at_ms": _ms(now), "client": "phone-tick"})
    assert r.json()["position_sec"] == 2400
    # A buffered save from 17 minutes earlier arrives late.
    caplog.set_level("INFO", logger="f7five0.api.podcasts")
    late = now.timestamp() - 17 * 60
    r = api.as_user(a).put(url, json={
        "position_sec": 1380, "recorded_at_ms": int(late * 1000), "client": "phone-buffer",
    })
    assert r.status_code == 200
    assert r.json()["position_sec"] == 2400
    db_session.expire_all()
    assert db_session.get(PodcastEpisodeProgress, (a.id, ep.id)).position_sec == 2400
    assert any("podcast_progress ignored" in m and "client=phone-buffer" in m for m in caplog.messages)


def test_a_newer_save_wins_even_when_it_rewinds(api, db_session):
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=7200)
    now = datetime.now(timezone.utc)
    url = f"/api/podcasts/episodes/{ep.id}/progress"
    api.as_user(a).put(url, json={"position_sec": 2400, "recorded_at_ms": _ms(now) - 30_000})
    r = api.as_user(a).put(url, json={"position_sec": 2385, "recorded_at_ms": _ms(now)})
    assert r.json()["position_sec"] == 2385


def test_a_save_without_a_time_counts_as_now(api, db_session):
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=7200)
    url = f"/api/podcasts/episodes/{ep.id}/progress"
    now = datetime.now(timezone.utc)
    api.as_user(a).put(url, json={"position_sec": 600, "recorded_at_ms": _ms(now) - 60_000})
    r = api.as_user(a).put(url, json={"position_sec": 300})
    assert r.json()["position_sec"] == 300
    # And a later timed save from before that is ignored.
    r = api.as_user(a).put(url, json={"position_sec": 900, "recorded_at_ms": _ms(now) - 30_000})
    assert r.json()["position_sec"] == 300


def test_a_clock_far_ahead_cannot_lock_out_later_saves(api, db_session):
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=7200)
    url = f"/api/podcasts/episodes/{ep.id}/progress"
    now = datetime.now(timezone.utc)
    api.as_user(a).put(url, json={"position_sec": 100, "recorded_at_ms": _ms(now) + 24 * 3600 * 1000})
    row = db_session.get(PodcastEpisodeProgress, (a.id, ep.id))
    db_session.refresh(row)
    held = row.client_recorded_at if row.client_recorded_at.tzinfo else row.client_recorded_at.replace(tzinfo=timezone.utc)
    assert (held - now).total_seconds() <= 125
    # A save from 3 minutes on (a correct clock) is accepted.
    r = api.as_user(a).put(url, json={"position_sec": 280, "recorded_at_ms": _ms(now) + 180_000})
    assert r.json()["position_sec"] == 280


def test_marking_unplayed_beats_an_older_save(api, db_session):
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=7200)
    url = f"/api/podcasts/episodes/{ep.id}/progress"
    now = datetime.now(timezone.utc)
    api.as_user(a).put(url, json={"position_sec": 500, "recorded_at_ms": _ms(now) - 120_000})
    api.as_user(a).delete(f"/api/podcasts/episodes/{ep.id}/played")
    r = api.as_user(a).put(url, json={"position_sec": 520, "recorded_at_ms": _ms(now) - 60_000})
    assert r.json()["position_sec"] == 0


def test_client_label_is_checked(api, db_session):
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod, duration=7200)
    url = f"/api/podcasts/episodes/{ep.id}/progress"
    r = api.as_user(a).put(url, json={"position_sec": 5, "client": "bad label; drop"})
    assert r.status_code == 422
