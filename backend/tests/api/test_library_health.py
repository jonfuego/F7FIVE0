"""Admin library health: health counts, missing-file list, DELETE endpoint."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.playback import WatchHistory
from app.models.track_play import TrackPlay
from app.models.user import User
from app.services import metadata_locks


_OLD = datetime.now(timezone.utc) - timedelta(days=10)
_NEW = datetime.now(timezone.utc) - timedelta(days=3)


def _user(db):
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", display_name="U",
             password_hash="x", role="member", is_active=True)
    db.add(u)
    db.flush()
    return u


def _movie(db, title="Test Movie"):
    m = Movie(title=title, tmdb_id=None)
    db.add(m)
    db.flush()
    return m


def _mf(db, movie, path, *, state=ScanState.missing, missing_since=None):
    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=movie.id,
        path=path,
        scan_state=state,
        missing_since=missing_since,
    )
    db.add(mf)
    db.flush()
    return mf


# Make all library folder roots look reachable (or not).
def _fake_folders(paths):
    """Patch _all_folder_roots and _reachable_roots to return given paths."""
    from app.api import admin_library_health
    return patch.multiple(
        admin_library_health,
        _all_folder_roots=lambda db: paths,
        _reachable_roots=lambda db: set(paths),
    )


# ---------------------------------------------------------------------------
# GET /api/admin/library/health
# ---------------------------------------------------------------------------
def test_health_returns_zero_counts_on_empty_db(client, db_session):
    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    assert r.status_code == 200
    body = r.json()
    assert body["missing_files_total"] == 0
    assert body["missing_files_eligible"] == 0
    assert body["probe_errors"] == 0
    assert body["unreachable_folders"] == 0


def test_health_counts_missing_files(client, db_session):
    m = _movie(db_session)
    _mf(db_session, m, r"D:\Movies\gone.mkv", state=ScanState.missing, missing_since=_OLD)
    _mf(db_session, m, r"D:\Movies\also_gone.mkv", state=ScanState.missing, missing_since=_NEW)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        r = client.get("/api/admin/library/health")
    body = r.json()
    assert body["missing_files_total"] == 2
    # Only the OLD file (>= 7 days) is eligible.
    assert body["missing_files_eligible"] == 1


def test_health_unreachable_folders(client, db_session):
    from app.api import admin_library_health

    with patch.multiple(
        admin_library_health,
        _all_folder_roots=lambda db: [r"D:\Movies", r"E:\Music"],
        _reachable_roots=lambda db: {r"D:\Movies"},  # E:\Music is unreachable
    ):
        r = client.get("/api/admin/library/health")
    assert r.json()["unreachable_folders"] == 1


# ---------------------------------------------------------------------------
# GET /api/admin/library/health/missing-files
# ---------------------------------------------------------------------------
def test_list_missing_files_returns_eligible_only(client, db_session):
    m = _movie(db_session, "Gone Movie")
    eligible_mf = _mf(db_session, m, r"D:\Movies\gone.mkv", missing_since=_OLD)
    _mf(db_session, m, r"D:\Movies\recent.mkv", missing_since=_NEW)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        r = client.get("/api/admin/library/health/missing-files")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["media_file_id"] == str(eligible_mf.id)
    assert items[0]["days_missing"] >= 7
    assert items[0]["item_title"] == "Gone Movie"


def test_list_missing_files_unreachable_folder_excluded(client, db_session):
    from app.api import admin_library_health

    m = _movie(db_session)
    _mf(db_session, m, r"E:\Unreachable\file.mkv", missing_since=_OLD)
    db_session.commit()

    with patch.multiple(
        admin_library_health,
        _all_folder_roots=lambda db: [r"E:\Unreachable"],
        _reachable_roots=lambda db: set(),  # folder is down
    ):
        r = client.get("/api/admin/library/health/missing-files")
    assert r.json() == []


# ---------------------------------------------------------------------------
# DELETE /api/admin/library/health/missing-files/{id}
# ---------------------------------------------------------------------------
def test_delete_removes_eligible_file(client, db_session):
    m = _movie(db_session)
    mf = _mf(db_session, m, r"D:\Movies\gone.mkv", missing_since=_OLD)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204

    # The media file and movie are gone.
    assert db_session.get(MediaFile, mf.id) is None
    assert db_session.get(Movie, m.id) is None


def test_delete_409_file_present(client, db_session):
    m = _movie(db_session)
    mf = _mf(db_session, m, r"D:\Movies\present.mkv", missing_since=_OLD)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=True):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 409
    assert r.json()["detail"] == "file_present"
    assert db_session.get(MediaFile, mf.id) is not None


def test_delete_409_not_eligible_too_recent(client, db_session):
    m = _movie(db_session)
    mf = _mf(db_session, m, r"D:\Movies\recent.mkv", missing_since=_NEW)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 409
    assert r.json()["detail"] == "not_eligible"
    assert db_session.get(MediaFile, mf.id) is not None


def test_delete_404_unknown_file(client, db_session):
    r = client.delete(f"/api/admin/library/health/missing-files/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# WatchHistory preservation: media_file_id becomes NULL, row survives
# ---------------------------------------------------------------------------
def test_delete_orphans_watch_history(client, db_session):
    u = _user(db_session)
    m = _movie(db_session)
    mf = _mf(db_session, m, r"D:\Movies\watched.mkv", missing_since=_OLD)
    now = datetime.now(timezone.utc)
    wh = WatchHistory(
        user_id=u.id, media_file_id=mf.id,
        started_at=now, last_position_sec=10,
        ref_kind="movie", ref_id=m.id, last_path=mf.path,
    )
    db_session.add(wh)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204

    # WatchHistory row still exists, but media_file_id is now NULL.
    db_session.expire(wh)
    wh_reloaded = db_session.get(WatchHistory, wh.id)
    assert wh_reloaded is not None
    assert wh_reloaded.media_file_id is None


# ---------------------------------------------------------------------------
# Album/Artist kept when track deleted (not deleted themselves)
# ---------------------------------------------------------------------------
def test_album_not_deleted_when_last_track_file_removed(client, db_session):
    from app.models.music import Album, Artist, Track

    artist = Artist(name="Test Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(title="Test Album", artist_id=artist.id)
    db_session.add(album)
    db_session.flush()
    track = Track(title="Track 1", album_id=album.id, track_number=1, disc_number=1)
    db_session.add(track)
    db_session.flush()
    mf = MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=r"D:\Music\Artist\Album\01 Track 1.flac",
        scan_state=ScanState.missing, missing_since=_OLD,
    )
    db_session.add(mf)
    db_session.commit()

    with _fake_folders([r"D:\Music"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204

    # Track was deleted, Album and Artist were not.
    assert db_session.get(Track, track.id) is None
    assert db_session.get(Album, album.id) is not None
    assert db_session.get(Artist, artist.id) is not None


# ---------------------------------------------------------------------------
# TrackPlay survives with track_id NULL after track deleted
# ---------------------------------------------------------------------------
def test_track_play_survives_with_null_track_id(client, db_session):
    from app.models.music import Album, Artist, Track

    u = _user(db_session)
    artist = Artist(name="Play Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(title="Play Album", artist_id=artist.id)
    db_session.add(album)
    db_session.flush()
    track = Track(title="Play Track", album_id=album.id, track_number=1, disc_number=1)
    db_session.add(track)
    db_session.flush()
    mf = MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=r"D:\Music\play.flac",
        scan_state=ScanState.missing, missing_since=_OLD,
    )
    db_session.add(mf)
    db_session.flush()
    tp = TrackPlay(
        user_id=u.id, track_id=track.id, ms_played=180000, completed=True,
        last_path=mf.path, ref_key="mbrec:test",
    )
    db_session.add(tp)
    db_session.commit()

    with _fake_folders([r"D:\Music"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204

    db_session.expire(tp)
    tp_reloaded = db_session.get(TrackPlay, tp.id)
    assert tp_reloaded is not None
    assert tp_reloaded.track_id is None


# ---------------------------------------------------------------------------
# Metadata locks cleared when item deleted
# ---------------------------------------------------------------------------
def test_delete_clears_metadata_locks(client, db_session):
    m = _movie(db_session)
    mf = _mf(db_session, m, r"D:\Movies\locked.mkv", missing_since=_OLD)
    metadata_locks.set_locks(db_session, "movie", m.id, ["title", "year"])
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204
    assert metadata_locks.locked_fields(db_session, "movie", m.id) == set()
