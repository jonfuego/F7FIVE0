"""Tests for the /api/recent home-shelf endpoint.

Covers the punch-list item 9 fix: a playable (ready) movie shows up in
recent, music videos stay out of the recent row, and a batch of freshly
scanned music videos (newer created_at) does not push a ready movie out of
the recent window so the home hero still has something to feature.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Artist, MusicVideo, MusicVideoRelease


def _add_movie(
    db, *, title: str, ready: bool = True,
    created_at: datetime | None = None,
) -> Movie:
    m = Movie(title=title)
    db.add(m)
    db.flush()
    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=m.id,
        path=f"\\\\nas\\movies\\{title}.mkv-{uuid.uuid4()}",
        scan_state=ScanState.ready if ready else ScanState.pending,
        duration_sec=5400,
    )
    if created_at is not None:
        mf.created_at = created_at
    db.add(mf)
    db.flush()
    return m


def _add_music_video(db, *, title: str, created_at: datetime) -> None:
    artist = Artist(name=f"Artist {title}")
    db.add(artist)
    db.flush()
    rel = MusicVideoRelease(
        artist_id=artist.id, title=f"Rel {title}", source_subpath=title,
    )
    db.add(rel)
    db.flush()
    mv = MusicVideo(
        release_id=rel.id, artist_id=artist.id, title=title,
        source_subpath=f"{title}.mp4",
    )
    db.add(mv)
    db.flush()
    mf = MediaFile(
        kind=MediaKind.music_video,
        ref_id=mv.id,
        path=f"\\\\nas\\mv\\{title}.mp4-{uuid.uuid4()}",
        scan_state=ScanState.ready,
        duration_sec=240,
    )
    mf.created_at = created_at
    db.add(mf)
    db.flush()


class TestRecent:
    def test_ready_movie_appears(self, client, db_session):
        _add_movie(db_session, title="The Burbs")
        db_session.commit()

        resp = client.get("/api/recent?limit=20")
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["kind"] == "movie"
        assert rows[0]["title"] == "The Burbs"

    def test_pending_movie_excluded(self, client, db_session):
        # A movie whose file has not probed is not watchable; it must not
        # show up as recent (clicking it would 409).
        _add_movie(db_session, title="Still Probing", ready=False)
        db_session.commit()

        resp = client.get("/api/recent?limit=20")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_music_videos_not_in_recent_row(self, client, db_session):
        # Music videos have their own home rail; they never show in this row.
        _add_music_video(
            db_session, title="Just A Video",
            created_at=datetime.now(timezone.utc),
        )
        db_session.commit()

        resp = client.get("/api/recent?limit=20")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_fresh_music_videos_do_not_crowd_out_a_movie(
        self, client, db_session,
    ):
        # The bug: the recent query pulled the newest files of any kind into
        # its dedupe window, then skipped music videos in Python. A big batch
        # of freshly scanned music videos (newer created_at) filled the whole
        # window and left the hero with nothing even though a ready movie
        # existed. Filtering music videos in the query fixes it.
        now = datetime.now(timezone.utc)
        old_movie = _add_movie(
            db_session, title="Old Movie", created_at=now - timedelta(days=30),
        )
        # More than the overshoot window (limit * 5) of newer music videos.
        for i in range(60):
            _add_music_video(
                db_session, title=f"MV {i}",
                created_at=now - timedelta(minutes=i),
            )
        db_session.commit()

        resp = client.get("/api/recent?limit=10")
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["kind"] == "movie"
        assert rows[0]["id"] == str(old_movie.id)


def _add_episodes(db, *, title: str, count: int) -> None:
    from app.models.tv import Episode, Series

    s = Series(title=title)
    db.add(s)
    db.flush()
    for n in range(1, count + 1):
        ep = Episode(series_id=s.id, season_number=1, episode_number=n)
        db.add(ep)
        db.flush()
        db.add(MediaFile(
            kind=MediaKind.episode, ref_id=ep.id,
            path=f"//nas/tv/{title}-{n}.mkv-{uuid.uuid4()}",
            scan_state=ScanState.ready, duration_sec=1800,
        ))
    db.flush()


def _add_album_tracks(db, *, title: str, count: int) -> None:
    from app.models.music import Album, Track

    artist = Artist(name=f"Artist {title}")
    db.add(artist)
    db.flush()
    album = Album(artist_id=artist.id, title=title)
    db.add(album)
    db.flush()
    for n in range(1, count + 1):
        t = Track(album_id=album.id, title=f"T{n}", track_number=n)
        db.add(t)
        db.flush()
        db.add(MediaFile(
            kind=MediaKind.track, ref_id=t.id,
            path=f"//nas/music/{title}-{n}.flac-{uuid.uuid4()}",
            scan_state=ScanState.ready, duration_sec=200,
        ))
    db.flush()


class TestBadgeMatchesRail:
    def test_badge_count_equals_rail_items(self, client, db_session):
        # Many files, few items: the raw file count is 2 + 12 + 10 + 3 = 27
        # but the rail shows 2 movies, 1 series, 1 album = 4 tiles. The
        # badge must say 4, not 27.
        from app.models.user import User

        now = datetime.now(timezone.utc)
        admin = db_session.query(User).filter_by(username="test-admin").one()
        admin.last_seen_home_at = now - timedelta(days=1)
        _add_movie(db_session, title="M1", created_at=now)
        _add_movie(db_session, title="M2", created_at=now)
        _add_movie(db_session, title="Probing", ready=False, created_at=now)
        _add_episodes(db_session, title="Show", count=12)
        _add_album_tracks(db_session, title="Album", count=10)
        for i in range(3):
            _add_music_video(db_session, title=f"MV{i}", created_at=now)
        db_session.commit()

        rail = client.get("/api/recent?limit=20").json()
        badge = client.get("/api/recent/badge").json()
        assert len(rail) == 4
        assert badge["count"] == len(rail)
