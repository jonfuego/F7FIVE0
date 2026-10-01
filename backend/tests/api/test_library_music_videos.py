"""Tests for the music-videos library endpoints.

Covers:
- artist-detail returning releases (release-grain, ordered by year)
- release-detail returning videos grouped by disc and ordered correctly
- recent-music-videos endpoint surfacing release_id, release_title,
  artist_name, and media_file_id
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Artist, MusicVideo, MusicVideoRelease


@pytest.fixture()
def fixture_artist(db_session):
    artist = Artist(name="New Order")
    db_session.add(artist)
    db_session.flush()
    return artist


def _add_video(
    db, *, release: MusicVideoRelease, title: str,
    disc_number: int = 1, track_number: int | None = None,
    ready: bool = True, source_subpath: str | None = None,
    created_at: datetime | None = None,
) -> tuple[MusicVideo, MediaFile | None]:
    mv = MusicVideo(
        release_id=release.id,
        artist_id=release.artist_id,
        title=title,
        disc_number=disc_number,
        track_number=track_number,
        source_subpath=source_subpath or f"{title}.mp4",
    )
    db.add(mv)
    db.flush()
    mf = None
    if ready:
        mf = MediaFile(
            kind=MediaKind.music_video,
            ref_id=mv.id,
            path=f"\\\\nas\\media\\{release.title}\\{title}.mp4-{uuid.uuid4()}",
            scan_state=ScanState.ready,
            duration_sec=240,
        )
        if created_at is not None:
            # MediaFile's created_at is server-side default; set explicitly
            # for ordering tests by clearing the default and setting.
            mf.created_at = created_at
        db.add(mf)
        db.flush()
    return mv, mf


# ---------------------------------------------------------------------------
# Artist detail returns releases
# ---------------------------------------------------------------------------
class TestArtistDetailReleases:
    def test_returns_releases_not_flat_videos(self, client, db_session, fixture_artist):
        rel_a = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Substance",
            source_subpath="Substance",
            release_year=1989,
        )
        rel_b = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Brotherhood",
            source_subpath="Brotherhood",
            release_year=1986,
        )
        db_session.add_all([rel_a, rel_b])
        db_session.flush()
        _add_video(db_session, release=rel_a, title="Bizarre Love Triangle")
        _add_video(db_session, release=rel_b, title="State of the Nation",
                   disc_number=1)
        _add_video(db_session, release=rel_b, title="True Faith",
                   disc_number=2)
        db_session.commit()

        resp = client.get(f"/api/music-videos/artists/{fixture_artist.id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "releases" in body
        # Sorted by release_year DESC NULLS LAST: 1989 (Substance) before 1986.
        titles = [r["title"] for r in body["releases"]]
        assert titles == ["Substance", "Brotherhood"]
        # Per-release counts.
        sub = next(r for r in body["releases"] if r["title"] == "Substance")
        bro = next(r for r in body["releases"] if r["title"] == "Brotherhood")
        assert sub["video_count"] == 1
        assert sub["disc_count"] == 1
        assert bro["video_count"] == 2
        assert bro["disc_count"] == 2

    def test_unscanned_releases_filtered_for_non_admin(
        self, client, db_session, fixture_artist,
    ):
        rel = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Empty",
            source_subpath="Empty",
        )
        db_session.add(rel)
        db_session.flush()
        # No ready files: this release should drop out of the response
        # for the default (member-style) caller.
        _add_video(db_session, release=rel, title="Phantom", ready=False)
        # Add another release with a ready file so the endpoint doesn't
        # 404 on "no playable releases".
        rel2 = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Substance",
            source_subpath="Substance",
            release_year=1989,
        )
        db_session.add(rel2)
        db_session.flush()
        _add_video(db_session, release=rel2, title="Real")
        db_session.commit()

        resp = client.get(f"/api/music-videos/artists/{fixture_artist.id}")
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["releases"]]
        assert titles == ["Substance"]


# ---------------------------------------------------------------------------
# Release detail
# ---------------------------------------------------------------------------
class TestReleaseDetail:
    def test_videos_grouped_by_disc_and_ordered(
        self, client, db_session, fixture_artist,
    ):
        rel = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Brotherhood",
            source_subpath="Brotherhood",
            release_year=1986,
        )
        db_session.add(rel)
        db_session.flush()
        # Disc 1: track 2, then track 1 (insertion order != desired sort).
        # Disc 2: missing track number, plus track 1.
        _add_video(db_session, release=rel, title="Z2", disc_number=1, track_number=2)
        _add_video(db_session, release=rel, title="A1", disc_number=1, track_number=1)
        _add_video(db_session, release=rel, title="Untracked", disc_number=2,
                   track_number=None)
        _add_video(db_session, release=rel, title="First", disc_number=2, track_number=1)
        db_session.commit()

        resp = client.get(f"/api/music-videos/releases/{rel.id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["artist_name"] == "New Order"
        assert body["disc_count"] == 2
        videos = body["videos"]
        # Order: (disc_number ASC, track_number ASC NULLS LAST, title ASC)
        order = [(v["disc_number"], v["track_number"], v["title"]) for v in videos]
        assert order == [
            (1, 1, "A1"),
            (1, 2, "Z2"),
            (2, 1, "First"),
            (2, None, "Untracked"),
        ]
        # Each video has a media_file_id when ready.
        assert all(v["media_file_id"] is not None for v in videos)

    def test_404_when_release_missing(self, client):
        bogus = uuid.uuid4()
        resp = client.get(f"/api/music-videos/releases/{bogus}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Recent music videos
# ---------------------------------------------------------------------------
class TestRecentMusicVideos:
    def test_includes_release_and_artist_context(
        self, client, db_session, fixture_artist,
    ):
        rel = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Substance",
            source_subpath="Substance",
            release_year=1989,
        )
        db_session.add(rel)
        db_session.flush()
        now = datetime.now(timezone.utc)
        _, mf_old = _add_video(
            db_session, release=rel, title="Old",
            created_at=now - timedelta(days=2),
        )
        _, mf_new = _add_video(
            db_session, release=rel, title="New",
            created_at=now,
        )
        db_session.commit()

        resp = client.get("/api/music-videos/recent?limit=10")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        # Most recent first.
        assert rows[0]["title"] == "New"
        # Required context fields per the spec.
        first = rows[0]
        assert first["release_id"] == str(rel.id)
        assert first["release_title"] == "Substance"
        assert first["artist_name"] == "New Order"
        assert first["media_file_id"] == str(mf_new.id)

    def test_unready_files_excluded(self, client, db_session, fixture_artist):
        rel = MusicVideoRelease(
            artist_id=fixture_artist.id,
            title="Substance",
            source_subpath="Substance",
        )
        db_session.add(rel)
        db_session.flush()
        # No ready file: should not show up.
        _add_video(db_session, release=rel, title="Pending", ready=False)
        db_session.commit()

        resp = client.get("/api/music-videos/recent?limit=10")
        assert resp.status_code == 200
        assert resp.json() == []
