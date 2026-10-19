"""Duplicate version and music-duplicate counts in library health."""
from __future__ import annotations

import uuid
from unittest.mock import patch

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track


def _fake_folders(paths):
    from app.api import admin_library_health
    return patch.multiple(
        admin_library_health,
        _all_folder_roots=lambda db: paths,
        _reachable_roots=lambda db: set(paths),
    )


def _movie(db, title="Dupe Movie") -> Movie:
    m = Movie(title=title)
    db.add(m)
    db.flush()
    return m


def _ready_mf(db, movie: Movie, path: str) -> MediaFile:
    mf = MediaFile(kind=MediaKind.movie, ref_id=movie.id,
                   path=path, scan_state=ScanState.ready)
    db.add(mf)
    db.flush()
    return mf


def _track_with_file(db, artist_name="Artist", album_title="Album",
                     title="Track", duration=200) -> tuple[Track, MediaFile]:
    artist = Artist(name=artist_name)
    db.add(artist)
    db.flush()
    album = Album(title=album_title, artist_id=artist.id)
    db.add(album)
    db.flush()
    track = Track(title=title, album_id=album.id, track_number=1, disc_number=1,
                  duration_sec=duration)
    db.add(track)
    db.flush()
    mf = MediaFile(kind=MediaKind.track, ref_id=track.id,
                   path=f"/music/{uuid.uuid4().hex}.flac", scan_state=ScanState.ready)
    db.add(mf)
    db.flush()
    return track, mf


# ---------------------------------------------------------------------------
# duplicate_movie_versions
# ---------------------------------------------------------------------------

def test_health_no_duplicate_versions_on_single_files(client, db_session):
    m = _movie(db_session)
    _ready_mf(db_session, m, r"D:\Movies\m.mkv")
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    assert r.status_code == 200
    assert r.json()["duplicate_movie_versions"] == 0


def test_health_counts_movie_with_two_versions(client, db_session):
    m = _movie(db_session)
    _ready_mf(db_session, m, r"D:\Movies\1080p.mkv")
    _ready_mf(db_session, m, r"D:\Movies\4k.mkv")
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    assert r.json()["duplicate_movie_versions"] == 1


def test_health_counts_multiple_movies_with_versions(client, db_session):
    m1 = _movie(db_session, "Movie A")
    _ready_mf(db_session, m1, r"D:\Movies\A_1.mkv")
    _ready_mf(db_session, m1, r"D:\Movies\A_2.mkv")
    m2 = _movie(db_session, "Movie B")
    _ready_mf(db_session, m2, r"D:\Movies\B_1.mkv")
    _ready_mf(db_session, m2, r"D:\Movies\B_2.mkv")
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    assert r.json()["duplicate_movie_versions"] == 2


# ---------------------------------------------------------------------------
# music_duplicates
# ---------------------------------------------------------------------------

def test_health_no_music_duplicates_when_unique(client, db_session):
    _track_with_file(db_session, title="Unique One")
    _track_with_file(db_session, title="Unique Two", artist_name="Other")
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    assert r.json()["music_duplicates"] == 0


def test_health_detects_same_tags_duplicate(client, db_session):
    _track_with_file(db_session, artist_name="Band", album_title="LP",
                     title="Song", duration=200)
    _track_with_file(db_session, artist_name="Band", album_title="LP",
                     title="Song", duration=202)
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    # Both tracks are in the duplicate set.
    assert r.json()["music_duplicates"] == 2


def test_health_no_duplicate_when_duration_far_apart(client, db_session):
    _track_with_file(db_session, artist_name="Band", album_title="LP",
                     title="Long Song", duration=200)
    _track_with_file(db_session, artist_name="Band", album_title="LP",
                     title="Long Song", duration=300)
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health")
    assert r.json()["music_duplicates"] == 0


# ---------------------------------------------------------------------------
# GET /api/admin/library/health/music-duplicates
# ---------------------------------------------------------------------------

def test_music_duplicates_endpoint_returns_groups(client, db_session):
    _track_with_file(db_session, artist_name="Duo", album_title="EP",
                     title="Hit", duration=180)
    _track_with_file(db_session, artist_name="Duo", album_title="EP",
                     title="Hit", duration=182)
    db_session.commit()

    with _fake_folders([]):
        r = client.get("/api/admin/library/health/music-duplicates")
    assert r.status_code == 200
    groups = r.json()
    assert len(groups) == 1
    assert groups[0]["reason"] == "same_tags"
    assert len(groups[0]["tracks"]) == 2


def test_music_duplicates_endpoint_empty(client, db_session):
    r = client.get("/api/admin/library/health/music-duplicates")
    assert r.status_code == 200
    assert r.json() == []
