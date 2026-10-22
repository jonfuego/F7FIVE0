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
from tests.test_library_scan import authed  # noqa: F401  (fixture used by name)


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


# ---------------------------------------------------------------------------
# ref_kind / ref_id preservation on orphaned WatchHistory
# ---------------------------------------------------------------------------
def test_watch_history_preserves_ref_fields_after_delete(client, db_session):
    """ref_kind and ref_id on WatchHistory remain set after media_file is removed."""
    u = _user(db_session)
    m = _movie(db_session)
    mf = _mf(db_session, m, r"D:\Movies\reffed.mkv", missing_since=_OLD)
    now = datetime.now(timezone.utc)
    wh = WatchHistory(
        user_id=u.id, media_file_id=mf.id,
        started_at=now, last_position_sec=20,
        ref_kind="movie", ref_id=m.id, last_path=mf.path,
    )
    db_session.add(wh)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204

    db_session.expire(wh)
    wh_reloaded = db_session.get(WatchHistory, wh.id)
    assert wh_reloaded is not None
    assert wh_reloaded.media_file_id is None
    assert wh_reloaded.ref_kind == "movie"
    assert wh_reloaded.ref_id == m.id
    assert wh_reloaded.last_path == mf.path


# ---------------------------------------------------------------------------
# Scan relinking: new MediaFile relinks orphaned WatchHistory
# ---------------------------------------------------------------------------
def test_rescan_relinks_watch_history_by_path(client, db_session):
    """After a movie is deleted, rescanning the same path relinks WatchHistory."""
    from app.services import history_keys

    u = _user(db_session)
    m = _movie(db_session)
    path = r"D:\Movies\relink.mkv"
    mf = _mf(db_session, m, path, missing_since=_OLD)
    now = datetime.now(timezone.utc)
    wh = WatchHistory(
        user_id=u.id, media_file_id=mf.id,
        started_at=now, last_position_sec=30,
        ref_kind="movie", ref_id=m.id, last_path=path,
    )
    db_session.add(wh)
    db_session.commit()

    # Delete the file via the health endpoint; movie and mf are removed.
    with _fake_folders([r"D:\Movies"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204
    db_session.expire_all()
    assert db_session.get(Movie, m.id) is None

    # WatchHistory survives with no media_file_id.
    wh_live = db_session.get(WatchHistory, wh.id)
    assert wh_live.media_file_id is None

    # Simulate a rescan: new Movie row at the same path.
    new_m = Movie(title="Test Movie")
    db_session.add(new_m)
    db_session.flush()
    new_mf = MediaFile(
        kind=MediaKind.movie, ref_id=new_m.id, path=path,
        scan_state=ScanState.missing,
    )
    db_session.add(new_mf)
    db_session.flush()

    history_keys.relink_history(db_session, new_mf)
    db_session.commit()

    db_session.expire(wh_live)
    wh_reloaded = db_session.get(WatchHistory, wh.id)
    assert wh_reloaded.media_file_id == new_mf.id


# ---------------------------------------------------------------------------
# Scan relinking: new track MediaFile relinks orphaned TrackPlay by path
# ---------------------------------------------------------------------------
def test_rescan_relinks_track_plays_by_path(client, db_session):
    """After a track is deleted, rescanning the same path relinks TrackPlay rows."""
    from app.models.music import Album, Artist, Track
    from app.services import history_keys

    u = _user(db_session)
    artist = Artist(name="Relink Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(title="Relink Album", artist_id=artist.id)
    db_session.add(album)
    db_session.flush()
    track = Track(title="Relink Track", album_id=album.id, track_number=1, disc_number=1)
    db_session.add(track)
    db_session.flush()
    path = r"D:\Music\relink.flac"
    mf = MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=path,
        scan_state=ScanState.missing, missing_since=_OLD,
    )
    db_session.add(mf)
    db_session.flush()
    tp = TrackPlay(
        user_id=u.id, track_id=track.id, ms_played=60000, completed=False,
        last_path=path,
    )
    db_session.add(tp)
    db_session.commit()

    # Delete: track and mf are removed; TrackPlay.track_id becomes NULL.
    with _fake_folders([r"D:\Music"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204
    db_session.expire_all()
    assert db_session.get(Track, track.id) is None

    tp_live = db_session.get(TrackPlay, tp.id)
    assert tp_live.track_id is None

    # Simulate a rescan: new track at the same path.
    new_artist = Artist(name="Relink Artist 2")
    db_session.add(new_artist)
    db_session.flush()
    new_album = Album(title="Relink Album 2", artist_id=new_artist.id)
    db_session.add(new_album)
    db_session.flush()
    new_track = Track(title="Relink Track 2", album_id=new_album.id, track_number=1, disc_number=1)
    db_session.add(new_track)
    db_session.flush()
    new_mf = MediaFile(
        kind=MediaKind.track, ref_id=new_track.id, path=path,
        scan_state=ScanState.missing,
    )
    db_session.add(new_mf)
    db_session.flush()

    history_keys.relink_history(db_session, new_mf)
    db_session.commit()

    db_session.expire(tp_live)
    tp_reloaded = db_session.get(TrackPlay, tp.id)
    assert tp_reloaded.track_id == new_track.id


# ---------------------------------------------------------------------------
# Album absent from browse list after last track file removed
# ---------------------------------------------------------------------------
def test_album_absent_from_albums_list_after_last_track_deleted(client, db_session):
    """An album whose only track is deleted is kept in the DB but hidden from browse."""
    from app.models.music import Album, Artist, Track

    artist = Artist(name="Hidden Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(title="Hidden Album", artist_id=artist.id)
    db_session.add(album)
    db_session.flush()
    track = Track(title="Hidden Track", album_id=album.id, track_number=1, disc_number=1)
    db_session.add(track)
    db_session.flush()
    mf = MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=r"D:\Music\hidden.flac",
        scan_state=ScanState.missing, missing_since=_OLD,
    )
    db_session.add(mf)
    db_session.commit()

    with _fake_folders([r"D:\Music"]):
        with patch("os.path.exists", return_value=False):
            r = client.delete(f"/api/admin/library/health/missing-files/{mf.id}")
    assert r.status_code == 204

    # Track was deleted, album and artist were not.
    db_session.expire_all()
    assert db_session.get(Track, track.id) is None
    assert db_session.get(Album, album.id) is not None

    # The album must not appear in the browse list (no ready tracks).
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert str(album.id) not in ids


# ---------------------------------------------------------------------------
# 1.0.18 review item 4: the count tiles drill down
# ---------------------------------------------------------------------------
def test_health_files_lists_every_missing_file_with_eligibility(client, db_session):
    m = _movie(db_session, "Gone Movie")
    _mf(db_session, m, r"D:\Movies\old.mkv", state=ScanState.missing, missing_since=_OLD)
    _mf(db_session, m, r"D:\Movies\new.mkv", state=ScanState.missing, missing_since=_NEW)
    _mf(db_session, m, r"D:\Movies\fine.mkv", state=ScanState.ready)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        r = client.get("/api/admin/library/health/files?state=missing")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    # Longest missing first.
    assert [i["path"] for i in body["items"]] == [r"D:\Movies\old.mkv", r"D:\Movies\new.mkv"]
    assert [i["eligible"] for i in body["items"]] == [True, False]
    assert body["items"][0]["item_title"] == "Gone Movie"
    assert body["items"][0]["days_missing"] >= 9
    assert body["items"][0]["kind"] == "movie"


def test_health_files_lists_probe_errors_and_pages(client, db_session):
    m = _movie(db_session)
    for i in range(3):
        _mf(db_session, m, rf"D:\Movies\bad{i}.mkv", state=ScanState.error)
    db_session.commit()

    with _fake_folders([r"D:\Movies"]):
        first = client.get("/api/admin/library/health/files?state=error&limit=2").json()
        rest = client.get("/api/admin/library/health/files?state=error&limit=2&offset=2").json()
    assert first["total"] == 3 and len(first["items"]) == 2 and len(rest["items"]) == 1
    assert all(i["state"] == "error" and i["days_missing"] is None for i in first["items"])
    paths = {i["path"] for i in first["items"] + rest["items"]}
    assert paths == {rf"D:\Movies\bad{i}.mkv" for i in range(3)}


def test_health_files_refuses_an_unknown_state(client):
    assert client.get("/api/admin/library/health/files?state=ready").status_code == 422


def test_unreachable_folders_lists_the_folders_the_service_cannot_open(client, db_session, monkeypatch):
    from app.api import admin_library_health
    from app.services import library_folders

    monkeypatch.setattr(library_folders, "all_folders", lambda db: {
        "movies": [r"\\nas\Movies"], "music": [r"\\nas\Music", r"\\gone\Music"],
    })
    monkeypatch.setattr(admin_library_health, "_reachable_roots", lambda db: {r"\\nas\Movies", r"\\nas\Music"})
    r = client.get("/api/admin/library/health/unreachable-folders")
    assert r.status_code == 200, r.text
    assert r.json() == [{"path": r"\\gone\Music", "library_kind": "music"}]


def test_the_drill_down_endpoints_are_admin_only(authed):
    client, _admin_h, member_h = authed  # noqa: F811
    assert client.get("/api/admin/library/health/files?state=missing", headers=member_h).status_code == 403
    assert client.get("/api/admin/library/health/unreachable-folders", headers=member_h).status_code == 403
