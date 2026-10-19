"""Unit tests for services/movie_versions.merge_twins."""
from __future__ import annotations

import uuid

from app.models.library import Library, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.services import movie_versions as mv


def _lib(db, name="Lib") -> Library:
    lib = Library(id=uuid.uuid4(), name=name, kind=LibraryKind.movies)
    db.add(lib)
    db.flush()
    return lib


def _movie(db, title="Film", *, tmdb_id=None, year=None) -> Movie:
    m = Movie(title=title, tmdb_id=tmdb_id, year=year)
    db.add(m)
    db.flush()
    return m


def _mf(db, movie: Movie, *, library: Library, path=None) -> MediaFile:
    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=movie.id,
        path=path or f"/movies/{uuid.uuid4().hex}.mkv",
        scan_state=ScanState.ready,
        library_id=library.id,
    )
    db.add(mf)
    db.flush()
    return mf


# ---------------------------------------------------------------------------
# _is_twin helper (no DB needed)
# ---------------------------------------------------------------------------

def test_is_twin_same_tmdb_id():
    a = Movie(title="Alpha", tmdb_id=1)
    b = Movie(title="Beta", tmdb_id=1)
    assert mv._is_twin(a, b) is True


def test_is_twin_different_tmdb_id():
    a = Movie(title="Alpha", tmdb_id=1)
    b = Movie(title="Beta", tmdb_id=2)
    assert mv._is_twin(a, b) is False


def test_is_twin_same_normalized_title_and_year():
    a = Movie(title="The Avengers", year=2012)
    b = Movie(title="avengers", year=2012)
    assert mv._is_twin(a, b) is True


def test_is_twin_different_year():
    a = Movie(title="Avengers", year=2012)
    b = Movie(title="Avengers", year=2019)
    assert mv._is_twin(a, b) is False


def test_is_twin_one_has_tmdb_one_not_title_match():
    a = Movie(title="The Matrix", tmdb_id=603, year=1999)
    b = Movie(title="Matrix", tmdb_id=None, year=1999)
    assert mv._is_twin(a, b) is True


# ---------------------------------------------------------------------------
# merge_twins
# ---------------------------------------------------------------------------

def test_merge_twins_by_title_and_year(db_session):
    lib = _lib(db_session)
    primary = _movie(db_session, "The Dark Knight", year=2008, tmdb_id=155)
    secondary = _movie(db_session, "Dark Knight", year=2008)
    _mf(db_session, primary, library=lib)
    _mf(db_session, secondary, library=lib)
    db_session.commit()

    deleted = mv.merge_twins(db_session)
    assert deleted == 1

    db_session.expire_all()
    from sqlalchemy import select
    remaining = db_session.scalars(select(Movie)).all()
    assert len(remaining) == 1
    assert remaining[0].tmdb_id == 155


def test_merge_twins_different_libraries_not_merged(db_session):
    lib_a = _lib(db_session, "LibA")
    lib_b = _lib(db_session, "LibB")
    a = _movie(db_session, "Inception", year=2010, tmdb_id=27205)
    b = _movie(db_session, "Inception", year=2010)
    _mf(db_session, a, library=lib_a)
    _mf(db_session, b, library=lib_b)
    db_session.commit()

    deleted = mv.merge_twins(db_session)
    assert deleted == 0


def test_merge_twins_no_twins(db_session):
    lib = _lib(db_session)
    _mf(db_session, _movie(db_session, "Movie A", tmdb_id=1, year=2000), library=lib)
    _mf(db_session, _movie(db_session, "Movie B", year=2001), library=lib)
    db_session.commit()

    deleted = mv.merge_twins(db_session)
    assert deleted == 0


def test_merge_twins_moves_media_files(db_session):
    lib = _lib(db_session)
    primary = _movie(db_session, "Twin Movie", year=2015, tmdb_id=9999)
    secondary = _movie(db_session, "Twin Movie", year=2015)
    mf_pri = _mf(db_session, primary, library=lib)
    mf_sec = _mf(db_session, secondary, library=lib)
    db_session.commit()

    mv.merge_twins(db_session)
    db_session.expire_all()

    from sqlalchemy import select
    survivors = db_session.scalars(select(Movie)).all()
    assert len(survivors) == 1
    all_files = db_session.scalars(
        select(MediaFile).where(MediaFile.kind == MediaKind.movie, MediaFile.ref_id == survivors[0].id)
    ).all()
    assert len(all_files) == 2
