"""Movie and episode version prefer endpoints."""
from __future__ import annotations

import uuid

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie


def _movie(db) -> Movie:
    m = Movie(title="Action Movie")
    db.add(m)
    db.flush()
    return m


def _mf(db, movie: Movie, *, path=None) -> MediaFile:
    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=movie.id,
        path=path or f"/movies/{uuid.uuid4().hex}.mkv",
        scan_state=ScanState.ready,
    )
    db.add(mf)
    db.flush()
    return mf


# ---------------------------------------------------------------------------
# POST /api/admin/library/movies/{movie_id}/versions/{media_file_id}/prefer
# ---------------------------------------------------------------------------

def test_prefer_version_sets_flag(client, db_session):
    m = _movie(db_session)
    mf1 = _mf(db_session, m)
    mf2 = _mf(db_session, m)
    db_session.commit()

    r = client.post(f"/api/admin/library/movies/{m.id}/versions/{mf1.id}/prefer")
    assert r.status_code == 204

    db_session.expire_all()
    assert db_session.get(MediaFile, mf1.id).is_preferred_version is True
    # Sibling should be cleared.
    assert db_session.get(MediaFile, mf2.id).is_preferred_version is None


def test_prefer_version_switches_preference(client, db_session):
    m = _movie(db_session)
    mf1 = _mf(db_session, m)
    mf2 = _mf(db_session, m)
    db_session.commit()

    client.post(f"/api/admin/library/movies/{m.id}/versions/{mf1.id}/prefer")
    r = client.post(f"/api/admin/library/movies/{m.id}/versions/{mf2.id}/prefer")
    assert r.status_code == 204

    db_session.expire_all()
    assert db_session.get(MediaFile, mf2.id).is_preferred_version is True
    assert db_session.get(MediaFile, mf1.id).is_preferred_version is None


def test_prefer_version_404_bad_movie(client, db_session):
    r = client.post(f"/api/admin/library/movies/{uuid.uuid4()}/versions/{uuid.uuid4()}/prefer")
    assert r.status_code == 404
    assert r.json()["detail"] == "movie_not_found"


def test_prefer_version_404_wrong_movie(client, db_session):
    m1 = _movie(db_session)
    m2 = _movie(db_session)
    mf = _mf(db_session, m2)
    db_session.commit()

    r = client.post(f"/api/admin/library/movies/{m1.id}/versions/{mf.id}/prefer")
    assert r.status_code == 404
    assert r.json()["detail"] == "media_file_not_found"


# ---------------------------------------------------------------------------
# POST /api/admin/library/episodes/{episode_id}/versions/{media_file_id}/prefer
# ---------------------------------------------------------------------------

def test_prefer_episode_version(client, db_session):
    from app.models.tv import Episode, Series

    series = Series(title="My Show")
    db_session.add(series)
    db_session.flush()
    ep = Episode(series_id=series.id, season_number=1, episode_number=1, title="Pilot")
    db_session.add(ep)
    db_session.flush()

    mf1 = MediaFile(kind=MediaKind.episode, ref_id=ep.id,
                    path=f"/tv/{uuid.uuid4().hex}.mkv", scan_state=ScanState.ready)
    mf2 = MediaFile(kind=MediaKind.episode, ref_id=ep.id,
                    path=f"/tv/{uuid.uuid4().hex}.mkv", scan_state=ScanState.ready)
    db_session.add_all([mf1, mf2])
    db_session.commit()

    r = client.post(f"/api/admin/library/episodes/{ep.id}/versions/{mf1.id}/prefer")
    assert r.status_code == 204

    db_session.expire_all()
    assert db_session.get(MediaFile, mf1.id).is_preferred_version is True
    assert db_session.get(MediaFile, mf2.id).is_preferred_version is None


def test_prefer_episode_version_404_bad_episode(client, db_session):
    r = client.post(f"/api/admin/library/episodes/{uuid.uuid4()}/versions/{uuid.uuid4()}/prefer")
    assert r.status_code == 404
    assert r.json()["detail"] == "episode_not_found"
