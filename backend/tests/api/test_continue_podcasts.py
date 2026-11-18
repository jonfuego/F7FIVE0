"""Podcast episodes on the Continue rail (/api/continue-watching?include_podcasts=true).

The phone's Home rail asks for them so an episode the person is partway
through sits next to the movie or album they were on, instead of only on the
Podcasts tab. Other clients do not ask and see exactly what they did before.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.art import ENTITY_PODCAST, ROLE_COVER, ArtOverride
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.playback import WatchProgress
from app.models.podcast import PodcastEpisodeProgress
from tests.podcast_helpers import make_episode, make_podcast, make_user

NOW = datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)


def _me(db_session):
    from app.api.deps import current_user
    from app.main import app

    user = app.dependency_overrides[current_user]()
    user = db_session.merge(user)
    db_session.flush()
    return user


def _listen(db, user, ep, *, position=600, at=NOW, played=False):
    db.add(PodcastEpisodeProgress(
        user_id=user.id, episode_id=ep.id, position_sec=position, duration_sec=3600,
        played_at=at if played else None, updated_at=at,
    ))
    db.flush()


def _movie_in_progress(db, user, *, at):
    movie = Movie(title="Dances with Wolves", year=1990)
    db.add(movie)
    db.flush()
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=movie.id, path=f"/m/{uuid.uuid4()}.mkv",
        scan_state=ScanState.ready, duration_sec=10800,
    )
    db.add(mf)
    db.flush()
    db.add(WatchProgress(
        user_id=user.id, media_file_id=mf.id, position_sec=600, duration_sec=10800,
        updated_at=at,
    ))
    db.flush()
    return movie


def test_not_included_unless_asked(client, db_session):
    user = _me(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    _listen(db_session, user, ep)
    db_session.commit()

    r = client.get("/api/continue-watching")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_episode_in_progress_is_on_the_rail(client, db_session):
    user = _me(db_session)
    pod = make_podcast(db_session, title="Hardcore History")
    ep = make_episode(db_session, pod, title="Supernova in the East")
    db_session.add(ArtOverride(
        entity_kind=ENTITY_PODCAST, entity_id=pod.id, role=ROLE_COVER,
        local_path="podcast/x/cover.jpg", source_kind="url", set_by=user.id,
    ))
    _listen(db_session, user, ep, position=900)
    db_session.commit()

    r = client.get("/api/continue-watching?include_podcasts=true")
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    it = items[0]
    assert it["kind"] == "podcast_episode"
    assert it["id"] == str(ep.id)
    assert it["podcast_id"] == str(pod.id)
    assert it["media_file_id"] is None
    assert it["title"] == "Supernova in the East"
    assert it["subtitle"] == "Hardcore History"
    assert it["position_sec"] == 900
    assert it["duration_sec"] == 3600
    assert it["poster_path"].startswith(f"/api/art/{ENTITY_PODCAST}/{pod.id}/{ROLE_COVER}")


def test_interleaved_with_video_by_recency(client, db_session):
    user = _me(db_session)
    _movie_in_progress(db_session, user, at=NOW - timedelta(hours=2))
    ep = make_episode(db_session, make_podcast(db_session))
    _listen(db_session, user, ep, at=NOW - timedelta(hours=1))
    db_session.commit()

    kinds = [it["kind"] for it in client.get(
        "/api/continue-watching?include_podcasts=true").json()]
    assert kinds == ["podcast_episode", "movie"]


def test_played_short_and_other_users_are_left_out(client, db_session):
    user = _me(db_session)
    other = make_user(db_session)
    played = make_episode(db_session, make_podcast(db_session, feed_url="https://a.example/f"))
    _listen(db_session, user, played, played=True)
    short = make_episode(db_session, make_podcast(db_session, feed_url="https://b.example/f"))
    _listen(db_session, user, short, position=5)
    theirs = make_episode(db_session, make_podcast(db_session, feed_url="https://c.example/f"))
    _listen(db_session, other, theirs)
    db_session.commit()

    assert client.get("/api/continue-watching?include_podcasts=true").json() == []


def test_one_tile_per_show_latest_episode(client, db_session):
    user = _me(db_session)
    pod = make_podcast(db_session)
    old = make_episode(db_session, pod, title="Old")
    new = make_episode(db_session, pod, title="New")
    _listen(db_session, user, old, at=NOW - timedelta(days=1))
    _listen(db_session, user, new, at=NOW)
    db_session.commit()

    items = client.get("/api/continue-watching?include_podcasts=true").json()
    assert [it["id"] for it in items] == [str(new.id)]


def test_limit_applies_after_the_merge(client, db_session):
    user = _me(db_session)
    _movie_in_progress(db_session, user, at=NOW - timedelta(hours=3))
    for i in range(3):
        ep = make_episode(
            db_session, make_podcast(db_session, feed_url=f"https://{i}.example/f"),
        )
        _listen(db_session, user, ep, at=NOW - timedelta(minutes=i))
    db_session.commit()

    items = client.get("/api/continue-watching?include_podcasts=true&limit=2").json()
    assert [it["kind"] for it in items] == ["podcast_episode", "podcast_episode"]
