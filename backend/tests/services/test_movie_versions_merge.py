"""Unit tests for services/movie_versions.merge_twins."""
from __future__ import annotations

import os
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


def test_merge_twins_idempotent(db_session):
    """Running merge_twins a second time on already-merged data changes nothing."""
    lib = _lib(db_session)
    primary = _movie(db_session, "Idempotent Film", year=2021, tmdb_id=54321)
    secondary = _movie(db_session, "Idempotent Film", year=2021)
    _mf(db_session, primary, library=lib)
    _mf(db_session, secondary, library=lib)
    db_session.commit()

    first = mv.merge_twins(db_session)
    assert first == 1

    # Second run: nothing left to merge.
    second = mv.merge_twins(db_session)
    assert second == 0


def test_scan_attach_second_file_same_library(db_session, tmp_path, monkeypatch):
    """The folder scan attaches a second file to an existing movie (matched by
    tmdb_id in the same root) instead of creating a separate twin Movie row."""
    from app.config import settings
    from app.models.user import User
    from app.services import ffprobe, scan_library
    from app.services.art import SYSTEM_USER_ID

    movies_root = tmp_path / "movies"
    movies_root.mkdir()
    monkeypatch.setattr(settings, "library_root_movies", str(movies_root))
    monkeypatch.setattr(settings, "radarr_api_key", "")
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    monkeypatch.setattr(settings, "path_rewrite_rules", "")

    def _probe(path, timeout=30.0):
        if not os.path.exists(path):
            return None
        return ffprobe.ProbeResult(
            container="mkv", size_bytes=os.path.getsize(path), duration_sec=120,
            bitrate_kbps=1000, video_codec="h264", audio_codec="aac",
            audio_channels=2, width=1920, height=1080,
        )

    monkeypatch.setattr(ffprobe, "probe", _probe)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", lambda *a, **k: None)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_artist", lambda *a, **k: None)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_album", lambda *a, **k: None)

    # system user is required for art-save code in the scan path.
    db_session.add(User(id=SYSTEM_USER_ID, username="system", display_name="System",
                        password_hash="!", role="admin", is_active=False))
    db_session.flush()

    # First scan: one file with a {tmdb-7777} tag in the folder name.
    p1 = movies_root / "Scan Movie (2005) {tmdb-7777}" / "Scan Movie.mkv"
    p1.parent.mkdir(parents=True)
    p1.write_bytes(b"\0" * 100)

    scan_library.scan_movies(db_session)

    from sqlalchemy import select as _select
    movies_after_first = db_session.scalars(_select(Movie)).all()
    assert len(movies_after_first) == 1
    movie = movies_after_first[0]
    assert movie.tmdb_id == 7777

    # Second scan: another folder with the same tmdb tag (same library root).
    p2 = movies_root / "Scan Movie (2005) {tmdb-7777} Bluray" / "Scan Movie Bluray.mkv"
    p2.parent.mkdir(parents=True)
    p2.write_bytes(b"\0" * 200)

    scan_library.scan_movies(db_session)
    db_session.expire_all()

    movies_after_second = db_session.scalars(_select(Movie)).all()
    assert len(movies_after_second) == 1, (
        "second file must attach to existing movie, not create a new Movie row"
    )

    files = db_session.scalars(
        _select(MediaFile).where(
            MediaFile.kind == MediaKind.movie,
            MediaFile.ref_id == movie.id,
        )
    ).all()
    assert len(files) == 2, "both files must be media_files of the one movie"
