"""Movie versions wiring (hand test L-08): the folder scan attaches a copy in
another folder of the same library as a second version, the folder scan job
folds twins older scans left behind (merge_twins), and the movie API lists the
default version first."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.library import Library, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.services import movie_versions as mv


def _lib(db, name="Movies") -> Library:
    lib = Library(id=uuid.uuid4(), name=name, kind=LibraryKind.movies)
    db.add(lib)
    db.flush()
    return lib


def _movie(db, title, *, year=None, tmdb_id=None) -> Movie:
    m = Movie(title=title, year=year, tmdb_id=tmdb_id)
    db.add(m)
    db.flush()
    return m


def _mf(db, movie, *, library, path=None, **kw) -> MediaFile:
    mf = MediaFile(kind=MediaKind.movie, ref_id=movie.id, scan_state=kw.pop("scan_state", ScanState.ready),
                   path=path or f"/movies/{uuid.uuid4().hex}.mkv", library_id=library.id, **kw)
    db.add(mf)
    db.flush()
    return mf


def _user(db, role="member"):
    from app.models.user import User
    u = User(id=uuid.uuid4(), username=f"u{uuid.uuid4().hex[:8]}", display_name="U",
             password_hash="x", role=role)
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# merge_twins keeps everything that hangs off the twin
# ---------------------------------------------------------------------------

def test_merge_keeps_history_progress_and_moves_refs(db_session):
    from app.models.collection import Collection, CollectionItem
    from app.models.metadata_lock import MetadataLock
    from app.models.playback import WatchHistory, WatchProgress

    lib = _lib(db_session)
    primary = _movie(db_session, "The Kid", year=1921, tmdb_id=10098)
    twin = _movie(db_session, "The Kid", year=1921)
    twin.overrides = {"tagline": "Six reels of joy"}
    mf_pri = _mf(db_session, primary, library=lib, is_preferred_version=True)
    mf_twin = _mf(db_session, twin, library=lib, is_preferred_version=True)
    user = _user(db_session)
    db_session.add(WatchHistory(user_id=user.id, media_file_id=mf_twin.id,
                                started_at=datetime.now(timezone.utc),
                                ref_kind="movie", ref_id=twin.id, last_path=mf_twin.path))
    db_session.add(WatchProgress(user_id=user.id, media_file_id=mf_twin.id, position_sec=300))
    db_session.add(MetadataLock(entity_kind="movie", entity_id=twin.id, field_name="tagline"))
    col = Collection(name="Chaplin", is_auto=False)
    db_session.add(col)
    db_session.flush()
    db_session.add(CollectionItem(collection_id=col.id, entity_kind="movie", entity_id=twin.id))
    db_session.commit()

    assert mv.merge_twins(db_session) == 1
    db_session.expire_all()

    assert db_session.get(Movie, twin.id) is None
    files = db_session.scalars(select(MediaFile).where(MediaFile.ref_id == primary.id)).all()
    assert {f.id for f in files} == {mf_pri.id, mf_twin.id}
    # One pinned version: the primary's.
    assert [f.id for f in files if f.is_preferred_version] == [mf_pri.id]
    wh = db_session.scalar(select(WatchHistory))
    assert wh.media_file_id == mf_twin.id and wh.ref_id == primary.id
    assert db_session.get(WatchProgress, (user.id, mf_twin.id)).position_sec == 300
    assert db_session.get(Movie, primary.id).overrides == {"tagline": "Six reels of joy"}
    assert db_session.scalars(select(MetadataLock.entity_id)).all() == [primary.id]
    assert db_session.scalars(select(CollectionItem.entity_id)).all() == [primary.id]


def test_merge_without_tmdb_keeps_the_oldest(db_session):
    lib = _lib(db_session)
    first = _movie(db_session, "The Kid", year=1921)
    first.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = _movie(db_session, "the kid", year=1921)
    second.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    _mf(db_session, second, library=lib)
    _mf(db_session, first, library=lib)
    db_session.commit()

    assert mv.merge_twins(db_session) == 1
    assert [m.id for m in db_session.scalars(select(Movie)).all()] == [first.id]


def test_merge_skips_movies_without_year_or_files(db_session):
    lib = _lib(db_session)
    _mf(db_session, _movie(db_session, "Heat"), library=lib)
    _mf(db_session, _movie(db_session, "Heat"), library=lib)
    _movie(db_session, "Alien", year=1979, tmdb_id=348)
    _movie(db_session, "Alien", year=1979)
    db_session.commit()
    assert mv.merge_twins(db_session) == 0


# ---------------------------------------------------------------------------
# The folder scan (L-08)
# ---------------------------------------------------------------------------

def _scan_env(monkeypatch, tmp_path):
    from app.config import settings
    from app.services import ffprobe, scan_library

    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key", "tmdb_api_key"):
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    monkeypatch.setattr(settings, "path_rewrite_rules", "")

    def _probe(path, timeout=30.0):
        if not os.path.exists(path):
            return None
        return ffprobe.ProbeResult(
            container="mkv", size_bytes=os.path.getsize(path), duration_sec=120,
            bitrate_kbps=1000, video_codec="h264", audio_codec="aac",
            audio_channels=2, width=1280, height=720 if "720p" in path else 1080,
        )

    monkeypatch.setattr(ffprobe, "probe", _probe)
    for name in ("schedule_enrich_movie", "schedule_enrich_artist", "schedule_enrich_album"):
        monkeypatch.setattr(scan_library.scheduler, name, lambda *a, **k: None)


def test_l08_second_folder_of_same_library_adds_a_version(db_session, client, tmp_path, monkeypatch):
    """C:\\Media\\Movies2 added as a second folder of the Movies library, with a
    copy of The Kid; no TMDB key. The scan gives one movie with two versions,
    and the movie API lists the default version first."""
    from app.models.user import User
    from app.services import library_folders, scan_library
    from app.services.art import SYSTEM_USER_ID

    _scan_env(monkeypatch, tmp_path)
    db_session.add(User(id=SYSTEM_USER_ID, username="system", display_name="System",
                        password_hash="!", role="admin", is_active=False))
    one, two = tmp_path / "Movies", tmp_path / "Movies2"
    (one / "The Kid (1921)").mkdir(parents=True)
    (one / "The Kid (1921)" / "The Kid (1921).mkv").write_bytes(b"\0" * 300)
    (two / "The Kid (1921)").mkdir(parents=True)
    (two / "The Kid (1921)" / "The Kid (1921) - 720p copy.mkv").write_bytes(b"\0" * 200)

    library_folders.save(db_session, {"movies": [str(one)]})
    scan_library.scan_movies(db_session)
    library_folders.save(db_session, {"movies": [str(one), str(two)]})
    stats = scan_library.scan_movies(db_session)
    assert stats.movies == 0

    movies = db_session.scalars(select(Movie)).all()
    assert [m.title for m in movies] == ["The Kid"]
    kid = movies[0]
    files = db_session.scalars(select(MediaFile).where(MediaFile.ref_id == kid.id)).all()
    assert len(files) == 2 and all(f.scan_state == ScanState.ready for f in files)
    assert len({f.library_id for f in files}) == 1

    r = client.get("/api/movies")
    listed = r.json()
    assert [m["title"] for m in listed] == ["The Kid"]
    detail = client.get(f"/api/movies/{kid.id}").json()
    assert [f["height"] for f in detail["media_files"]] == [1080, 720]

    # An admin pins the 720p copy: it is listed (and so played) first.
    copy = next(f for f in files if "720p" in f.path)
    r = client.post(f"/api/admin/library/movies/{kid.id}/versions/{copy.id}/prefer")
    assert r.status_code == 204
    detail = client.get(f"/api/movies/{kid.id}").json()
    assert detail["media_files"][0]["id"] == str(copy.id)
    assert detail["media_files"][0]["is_preferred"] is True


def test_movie_api_lists_missing_versions_last(db_session):
    from app.services.version_pick import sort_versions

    lib = _lib(db_session)
    m = _movie(db_session, "Heat", year=1995)
    gone = _mf(db_session, m, library=lib, height=2160, scan_state=ScanState.missing)
    low = _mf(db_session, m, library=lib, height=720)
    high = _mf(db_session, m, library=lib, height=1080)
    assert [f.id for f in sort_versions([gone, low, high])] == [high.id, low.id, gone.id]


# ---------------------------------------------------------------------------
# The folder scan job runs merge_twins
# ---------------------------------------------------------------------------

class _Sched:
    def add_job(self, func, **kw):
        pass


def _patch_scan_job(monkeypatch, db_session):
    from app import scheduler
    monkeypatch.setattr(scheduler, "_scheduler", _Sched())
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(scheduler.nas_auth, "ensure_all", lambda db: None)
    monkeypatch.setattr(scheduler.scan_library, "scan_all", lambda db, on_progress=None: None)
    monkeypatch.setattr(scheduler.scan_library, "schedule_catch_up", lambda db: {})
    return scheduler


def test_folder_scan_job_merges_twins_left_by_older_scans(db_session, monkeypatch):
    lib = _lib(db_session)
    first = _movie(db_session, "The Kid", year=1921)
    second = _movie(db_session, "The Kid", year=1921)
    _mf(db_session, first, library=lib)
    _mf(db_session, second, library=lib)
    db_session.commit()

    _patch_scan_job(monkeypatch, db_session)._scan_folders()

    db_session.expire_all()
    movies = db_session.scalars(select(Movie)).all()
    assert len(movies) == 1
    assert len(db_session.scalars(select(MediaFile).where(MediaFile.ref_id == movies[0].id)).all()) == 2


def test_folder_scan_job_survives_a_failing_merge(db_session, monkeypatch):
    from app.services import scan_status

    def boom(db):
        raise RuntimeError("merge broke")

    scheduler = _patch_scan_job(monkeypatch, db_session)
    monkeypatch.setattr(mv, "merge_twins", boom)
    scheduler._scan_folders()

    status = scan_status.read(db_session)
    assert status["state"] == "idle" and status["last_error"] is None
