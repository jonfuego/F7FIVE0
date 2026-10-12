"""Feed parsing, refresh (conditional GET, upsert, failures, status) and
auto-download."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.models.podcast import Podcast, PodcastEpisode
from app.services import net_guard, scan_status
from app.services.podcasts import feed as feed_service
from app.services.podcasts import refresh
from tests.podcast_helpers import (
    fixture_bytes, install_dns, install_transport, make_podcast, make_user, subscribe,
)


@pytest.fixture(autouse=True)
def _net(monkeypatch):
    install_dns(monkeypatch)
    monkeypatch.setattr(refresh, "sync_art", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_parse_reads_rss_itunes_and_podcast_tags():
    parsed = feed_service.parse_feed(fixture_bytes("feed.xml"), "https://fixture.example/feed.xml")
    assert parsed.title == "The Fixture Show"
    assert parsed.author == "Fixture Co"
    assert parsed.art_url == "https://fixture.example/art.jpg"
    assert parsed.podcast_guid == "ead4c236-bf58-58c6-a2c6-a6b28d128cb6"
    assert len(parsed.episodes) == 3
    three, two, one = parsed.episodes
    assert three.guid == "fixture-ep-3"
    assert three.enclosure_url == "https://cdn.fixture.example/ep3.mp3"
    assert three.enclosure_type == "audio/mpeg" and three.enclosure_length == 12345
    assert three.duration_sec == 3723
    assert three.season == 2 and three.episode == 3
    assert three.chapters_url == "https://fixture.example/ep3.chapters.json"
    assert three.published_at == datetime(2025, 3, 1, 8, 0, tzinfo=timezone.utc)
    assert two.duration_sec == 1800
    assert two.season == 2 and two.episode == 2
    assert one.guid is None
    assert one.duration_sec == 750


def test_descriptions_are_plain_text_with_entities_unescaped():
    parsed = feed_service.parse_feed(fixture_bytes("feed.xml"))
    assert "<" not in parsed.description and ">" not in parsed.description
    assert parsed.description == "A show about fixtures & tests."
    three, two, one = parsed.episodes
    assert three.description == "Hello & welcome to the show."
    assert "alert" not in three.description
    assert "<" not in two.description and "&amp;" not in two.description
    assert two.description.replace("\n", " ").split() == ["Second", "&", "final", "line"]
    assert one.description == "Plain text only, Tom & Jerry."


def test_plain_text_strips_tags_scripts_and_unescapes():
    assert feed_service.plain_text("<p>One</p><p>Two &amp; &lt;three&gt;</p>") == "One\n\nTwo & <three>"
    assert feed_service.plain_text("<style>p{}</style>x<script>evil()</script>y") == "xy"
    assert feed_service.plain_text("a&nbsp;b") == "a b"
    assert feed_service.plain_text(None) == ""


def test_entity_expansion_feed_is_refused_fast():
    started = time.monotonic()
    with pytest.raises(feed_service.FeedError):
        feed_service.parse_feed(fixture_bytes("billion_laughs.xml"))
    assert time.monotonic() - started < 2.0


def test_garbage_is_a_feed_error_not_a_crash():
    with pytest.raises(feed_service.FeedError):
        feed_service.parse_feed(b"<html><body>not a feed</body></html>")
    with pytest.raises(feed_service.FeedError):
        feed_service.parse_feed(b"")


def test_a_slightly_broken_feed_still_parses():
    body = fixture_bytes("feed.xml").replace(b"Tom &amp; Jerry", b"Tom & Jerry")
    parsed = feed_service.parse_feed(body)
    assert len(parsed.episodes) == 3


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
FEED_URL = "https://fixture.example/feed.xml"


def _feed_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, content=fixture_bytes("feed.xml"),
        headers={"etag": '"abc123"', "last-modified": "Sat, 01 Mar 2025 09:00:00 GMT",
                 "content-type": "application/rss+xml"},
    )


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_refresh_creates_the_show_and_episodes(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    out = refresh.refresh_podcast(db_session, pod)
    db_session.commit()
    assert out.status == "updated" and len(out.new_episode_ids) == 3
    assert pod.title == "The Fixture Show" and pod.author == "Fixture Co"
    assert pod.etag == '"abc123"' and pod.last_modified == "Sat, 01 Mar 2025 09:00:00 GMT"
    assert pod.last_error is None and pod.last_checked_at is not None
    assert pod.podcast_guid == "ead4c236-bf58-58c6-a2c6-a6b28d128cb6"
    assert _count(db_session, PodcastEpisode) == 3
    descs = db_session.scalars(select(PodcastEpisode.description)).all()
    assert all("<" not in (d or "") for d in descs)


def test_conditional_get_sends_validators_and_a_304_changes_nothing(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    refresh.refresh_podcast(db_session, pod)
    db_session.commit()
    before = {e.guid: (e.title, e.description) for e in db_session.scalars(select(PodcastEpisode))}
    stamp = pod.last_checked_at

    seen = {}

    def not_modified(request: httpx.Request) -> httpx.Response:
        seen["inm"] = request.headers.get("if-none-match")
        seen["ims"] = request.headers.get("if-modified-since")
        return httpx.Response(304)

    install_transport(monkeypatch, not_modified)
    time.sleep(0.01)
    out = refresh.refresh_podcast(db_session, pod)
    db_session.commit()
    assert seen == {"inm": '"abc123"', "ims": "Sat, 01 Mar 2025 09:00:00 GMT"}
    assert out.status == "not_modified" and out.new_episode_ids == []
    assert pod.last_checked_at >= stamp and pod.last_error is None
    after = {e.guid: (e.title, e.description) for e in db_session.scalars(select(PodcastEpisode))}
    assert after == before


def test_upsert_by_guid_does_not_duplicate_and_updates(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    refresh.refresh_podcast(db_session, pod)
    db_session.commit()

    changed = fixture_bytes("feed.xml").replace(b"<title>Episode Three</title>", b"<title>Episode Three (fixed)</title>")
    install_transport(monkeypatch, lambda r: httpx.Response(200, content=changed))
    out = refresh.refresh_podcast(db_session, pod)
    db_session.commit()
    assert out.new_episode_ids == []
    assert _count(db_session, PodcastEpisode) == 3
    titles = {e.guid: e.title for e in db_session.scalars(select(PodcastEpisode))}
    assert titles["fixture-ep-3"] == "Episode Three (fixed)"


def test_missing_guid_falls_back_to_the_enclosure_url(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    refresh.refresh_podcast(db_session, pod)
    refresh.refresh_podcast(db_session, pod)
    db_session.commit()
    guids = sorted(db_session.scalars(select(PodcastEpisode.guid)).all())
    assert "https://cdn.fixture.example/ep1.mp3" in guids
    assert _count(db_session, PodcastEpisode) == 3


def test_failed_fetch_records_the_error_and_keeps_old_episodes(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    refresh.refresh_podcast(db_session, pod)
    db_session.commit()

    install_transport(monkeypatch, lambda r: httpx.Response(500, content=b"boom"))
    out = refresh.refresh_podcast(db_session, pod)
    db_session.commit()
    assert out.status == "error" and out.error
    assert pod.last_error and "500" in pod.last_error
    assert _count(db_session, PodcastEpisode) == 3

    install_transport(monkeypatch, _feed_response)
    refresh.refresh_podcast(db_session, pod)
    assert pod.last_error is None


def test_feed_over_the_size_cap_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(net_guard, "FEED_MAX_BYTES", 2000)
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    out = refresh.refresh_podcast(db_session, pod)
    assert out.status == "error"
    assert _count(db_session, PodcastEpisode) == 0
    assert pod.last_error


def test_entity_expansion_feed_leaves_the_show_alone(db_session, monkeypatch):
    install_transport(monkeypatch, lambda r: httpx.Response(200, content=fixture_bytes("billion_laughs.xml")))
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    started = time.monotonic()
    out = refresh.refresh_podcast(db_session, pod)
    assert time.monotonic() - started < 2.0
    assert out.status == "error" and _count(db_session, PodcastEpisode) == 0


def test_refresh_to_a_private_feed_url_is_an_error_and_sends_nothing(db_session, monkeypatch):
    calls = install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title="x", feed_url="http://10.0.0.5/feed.xml")
    out = refresh.refresh_podcast(db_session, pod)
    assert out.status == "error" and len(calls) == 0


# ---------------------------------------------------------------------------
# Auto-download
# ---------------------------------------------------------------------------
def test_auto_download_queues_only_new_episodes_after_the_subscription(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    user = make_user(db_session)
    # Episode Three (2025-03-01) and Two (2025-02-01) come after; One (2024) does not.
    subscribe(db_session, user, pod, auto_download=True,
              created_at=datetime(2025, 1, 15, tzinfo=timezone.utc))
    queued: list = []
    out = refresh.refresh_podcast(db_session, pod, queue_download=queued.append)
    db_session.commit()
    by_guid = {e.guid: e.id for e in db_session.scalars(select(PodcastEpisode))}
    assert sorted(queued) == sorted([by_guid["fixture-ep-3"], by_guid["fixture-ep-2"]])
    assert len(out.new_episode_ids) == 3

    queued.clear()
    refresh.refresh_podcast(db_session, pod, queue_download=queued.append)
    assert queued == []


def test_auto_download_off_queues_nothing(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    user = make_user(db_session)
    subscribe(db_session, user, pod, auto_download=False,
              created_at=datetime(2025, 1, 15, tzinfo=timezone.utc))
    queued: list = []
    refresh.refresh_podcast(db_session, pod, queue_download=queued.append)
    assert queued == []


def test_any_subscriber_with_auto_download_is_enough(db_session, monkeypatch):
    install_transport(monkeypatch, _feed_response)
    pod = make_podcast(db_session, title=FEED_URL, feed_url=FEED_URL)
    a, b = make_user(db_session), make_user(db_session)
    subscribe(db_session, a, pod, auto_download=False, created_at=datetime(2025, 1, 15, tzinfo=timezone.utc))
    subscribe(db_session, b, pod, auto_download=True, created_at=datetime(2025, 2, 15, tzinfo=timezone.utc))
    queued: list = []
    refresh.refresh_podcast(db_session, pod, queue_download=queued.append)
    # Only Episode Three is after B's subscription.
    assert len(queued) == 1


# ---------------------------------------------------------------------------
# refresh_all and its status
# ---------------------------------------------------------------------------
def test_refresh_all_only_touches_shows_with_a_subscriber_and_tracks_status(db_session, monkeypatch):
    states: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        states.append(scan_status.pr_read(db_session)["state"])
        return _feed_response(request)

    install_transport(monkeypatch, handler)
    watched = make_podcast(db_session, title="w", feed_url=FEED_URL)
    make_podcast(db_session, title="n", feed_url="https://nobody.example/feed.xml")
    make_podcast(db_session, title="local", feed_url=None, source="local")
    user = make_user(db_session)
    subscribe(db_session, user, watched)
    assert scan_status.pr_read(db_session)["state"] == "idle"

    stats = refresh.refresh_all(db_session, queue_download=lambda _id: None)
    assert states == ["running"]
    status = scan_status.pr_read(db_session)
    assert status["state"] == "idle" and status["finished_at"] and status["started_at"]
    assert status["total"] == 1 and status["count"] == 1 and status["errors"] == 0
    assert status["added"] == 3
    assert stats.shows == 1 and stats.new_episodes == 3


def test_refresh_all_counts_a_failing_show_and_keeps_going(db_session, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bad.example":
            return httpx.Response(503)
        return _feed_response(request)

    install_transport(monkeypatch, handler)
    good = make_podcast(db_session, title="g", feed_url=FEED_URL)
    bad = make_podcast(db_session, title="b", feed_url="https://bad.example/feed.xml")
    user = make_user(db_session)
    subscribe(db_session, user, good)
    subscribe(db_session, user, bad)
    refresh.refresh_all(db_session, queue_download=lambda _id: None)
    status = scan_status.pr_read(db_session)
    assert status["state"] == "idle" and status["errors"] == 1 and status["count"] == 2
    assert bad.last_error and good.last_error is None


def test_a_stale_running_refresh_status_turns_idle_on_startup(db_session):
    assert scan_status.pr_begin(db_session) is True
    assert scan_status.pr_begin(db_session) is False
    db_session.commit()
    assert scan_status.pr_read(db_session)["state"] == "running"
    assert scan_status.reset_stale(db_session) is True
    status = scan_status.pr_read(db_session)
    assert status["state"] == "idle" and "interrupted" in status["last_error"]
    assert scan_status.KEY != scan_status.PODCAST_KEY and scan_status.PODCAST_KEY == "podcast_refresh_status"
