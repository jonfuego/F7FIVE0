"""Folder scans that save as they go, enrichment after commit, the scan status
and the Admin / signed-in endpoints around them.

The batch tests run on a file-backed SQLite database, not the shared
in-memory one. The in-memory engine reuses a single connection, so a second
session there would see uncommitted rows and prove nothing. With a file and
WAL, a second session sees only what the scan has committed.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app import scheduler
from app.config import settings
from app.models.media_file import MediaFile
from app.models.movie import Movie
from app.models.music import Album, Artist
from app.models.tv import Episode
from app.services import ffprobe, scan_library


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def file_db(engine, tmp_path, monkeypatch):
    """Session factory on a file-backed database. Also what the scheduler's
    folder-scan job opens, so the whole job runs against it."""
    import app.models  # noqa: F401
    from app.db import Base

    eng = create_engine(f"sqlite:///{tmp_path / 'scan.db'}", future=True, connect_args={"timeout": 5})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(scheduler, "SessionLocal", factory, raising=False)
    yield factory
    eng.dispose()


@pytest.fixture()
def libs(tmp_path, monkeypatch):
    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key", "tmdb_api_key"):
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    roots = {k: tmp_path / k for k in ("movies", "tv", "music")}
    for k, p in roots.items():
        p.mkdir()
        monkeypatch.setattr(settings, f"library_root_{k}", str(p))
    monkeypatch.setattr(settings, "library_root_music_videos", "")
    return roots


def _touch(path: Path, size: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def _make_movies(root: Path, n: int, *, tmdb: bool = False) -> None:
    for i in range(1, n + 1):
        tag = f" {{tmdb-{1000 + i}}}" if tmdb else ""
        _touch(root / f"Movie {i:03d} (2000){tag}" / f"Movie {i:03d} (2000).mkv")


def _fake_probe(monkeypatch, hook=None):
    """ffprobe stand-in. `hook(n)` runs on the n-th probe, before it answers."""
    calls = []

    def _probe(path, timeout=30.0):
        calls.append(path)
        if hook is not None:
            hook(len(calls))
        if not os.path.exists(path):
            return None
        return ffprobe.ProbeResult(
            container="mkv", size_bytes=os.path.getsize(path), duration_sec=120,
            bitrate_kbps=1000, video_codec="h264", audio_codec="aac",
            audio_channels=2, width=1920, height=1080,
        )

    monkeypatch.setattr(ffprobe, "probe", _probe)
    return calls


def _count(factory, model) -> int:
    with factory() as other:
        return other.scalar(select(func.count()).select_from(model))


def _all(factory, model) -> list:
    with factory() as other:
        return other.scalars(select(model)).all()


# ---------------------------------------------------------------------------
# Batch saves
# ---------------------------------------------------------------------------
def test_scan_saves_in_batches_so_another_session_sees_rows_mid_scan(file_db, libs, monkeypatch):
    _make_movies(libs["movies"], 60)
    mid = {}

    def hook(n):
        if n == 40:
            mid["movies"] = _count(file_db, Movie)

    _fake_probe(monkeypatch, hook)
    with file_db() as db:
        scan_library.scan_all(db)
        db.commit()

    assert mid["movies"] >= 25, "rows found so far must be visible before the scan ends"
    assert mid["movies"] < 60
    assert _count(file_db, Movie) == 60
    assert scan_library.BATCH_SIZE == 25


def test_scan_that_raises_midway_keeps_what_it_committed(file_db, libs, monkeypatch):
    _make_movies(libs["movies"], 60)
    _touch(libs["tv"] / "Show (2010)" / "Season 01" / "Show - S01E01 - Pilot.mkv")

    def hook(n):
        if n == 40:
            raise RuntimeError("share went away")

    _fake_probe(monkeypatch, hook)
    with file_db() as db:
        total = scan_library.scan_all(db)
        db.commit()

    kept = _count(file_db, Movie)
    assert 25 <= kept < 40, f"the first batch was committed and survives; got {kept}"
    assert total.errors >= 1
    # One library failing does not undo (or stop) another.
    assert _count(file_db, Episode) == 1


# ---------------------------------------------------------------------------
# Enrichment runs on saved rows
# ---------------------------------------------------------------------------
def test_movie_enrichment_is_scheduled_only_for_committed_rows(file_db, libs, monkeypatch):
    from app.services.metadata import runner

    _make_movies(libs["movies"], 30, tmdb=True)
    _fake_probe(monkeypatch)
    scheduled = []

    def record(movie_id, *_a, **_k):
        with file_db() as other:
            committed = other.get(Movie, movie_id) is not None
            found = runner.enrich_movie(other, movie_id).notes != "movie_not_found"
        scheduled.append((movie_id, committed, found))

    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", record)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_artist", lambda *_a, **_k: None)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_album", lambda *_a, **_k: None)

    with file_db() as db:
        scan_library.scan_all(db)
        db.commit()

    assert len(scheduled) == 30
    assert len({s[0] for s in scheduled}) == 30
    assert all(committed for _id, committed, _f in scheduled), "scheduled before the row was committed"
    assert all(found for _id, _c, found in scheduled), "enrich_movie could not find the movie"


def test_artist_and_album_enrichment_wait_for_the_commit(file_db, libs, monkeypatch):
    _fake_probe(monkeypatch)
    for i in range(1, 4):
        _touch(libs["music"] / f"Artist {i}" / f"Album {i}" / "01 - Song.flac")

    def tags(path):
        n = Path(path).parts[-3].split()[-1]
        return {
            "albumartist": f"Artist {n}", "album": f"Album {n}", "title": "Song", "tracknumber": "1",
            "musicbrainz_albumartistid": str(uuid.UUID(int=int(n))),
            "musicbrainz_releasegroupid": str(uuid.UUID(int=100 + int(n))),
        }

    monkeypatch.setattr(scan_library, "read_tags", tags)
    seen = {"artist": [], "album": []}

    def rec_artist(artist_id, *_a, **_k):
        with file_db() as other:
            seen["artist"].append(other.get(Artist, artist_id) is not None)

    def rec_album(album_id, *_a, **_k):
        with file_db() as other:
            seen["album"].append(other.get(Album, album_id) is not None)

    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", lambda *_a, **_k: None)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_artist", rec_artist)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_album", rec_album)

    with file_db() as db:
        scan_library.scan_all(db)
        db.commit()

    assert seen["artist"] == [True, True, True]
    assert seen["album"] == [True, True, True]


def test_sync_collects_enrichment_for_after_the_commit(db_session, monkeypatch):
    from app.services import sync

    stats = sync.SyncStats()
    called = []
    monkeypatch.setattr(sync.scheduler, "schedule_enrich_movie", lambda i, *a, **k: called.append(("movie", i)))
    monkeypatch.setattr(sync.scheduler, "schedule_enrich_artist", lambda i, *a, **k: called.append(("artist", i)))
    monkeypatch.setattr(sync.scheduler, "schedule_enrich_album", lambda i, *a, **k: called.append(("album", i)))

    payload = {"id": 7, "tmdbId": 603, "title": "The Matrix", "year": 1999, "images": []}
    monkeypatch.setattr(sync, "download_art_on_sync", lambda *a, **k: None)
    movie = sync._upsert_movie(db_session, payload, stats)
    assert called == [], "enrichment must not be scheduled while the sync transaction is open"

    sync.schedule_pending_enrichment(stats)
    assert called == [("movie", movie.id)]
    sync.schedule_pending_enrichment(stats)
    assert called == [("movie", movie.id)], "pending ids are handed over once"


# ---------------------------------------------------------------------------
# One-time catch-up
# ---------------------------------------------------------------------------
def test_catch_up_schedules_unenriched_rows_with_an_id_and_skips_the_rest(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "test-key")
    now = datetime.now(timezone.utc)
    stale_movie = Movie(title="Stale", tmdb_id=1)
    fresh_movie = Movie(title="Fresh", tmdb_id=2, metadata_synced_at=now)
    no_id_movie = Movie(title="No id")
    stale_artist = Artist(name="Stale A", mbid="m-1")
    fresh_artist = Artist(name="Fresh A", mbid="m-2", metadata_synced_at=now)
    no_id_artist = Artist(name="No id A")
    db_session.add_all([stale_movie, fresh_movie, no_id_movie, stale_artist, fresh_artist, no_id_artist])
    db_session.flush()
    stale_album = Album(artist_id=stale_artist.id, title="Stale Al", mbid="a-1")
    fresh_album = Album(artist_id=stale_artist.id, title="Fresh Al", mbid="a-2", metadata_synced_at=now)
    db_session.add_all([stale_album, fresh_album])
    db_session.commit()

    got = {"movie": [], "artist": [], "album": []}
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", lambda i, *a, **k: got["movie"].append(i))
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_artist", lambda i, *a, **k: got["artist"].append(i))
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_album", lambda i, *a, **k: got["album"].append(i))

    counts = scan_library.schedule_catch_up(db_session)

    assert got == {"movie": [stale_movie.id], "artist": [stale_artist.id], "album": [stale_album.id]}
    assert counts == {"movies": 1, "artists": 1, "albums": 1}


def test_catch_up_leaves_movies_alone_while_there_is_no_tmdb_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    db_session.add(Movie(title="Stale", tmdb_id=1))
    db_session.commit()
    got = []
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", lambda i, *a, **k: got.append(i))
    assert scan_library.schedule_catch_up(db_session)["movies"] == 0
    assert got == []


# ---------------------------------------------------------------------------
# Scan status
# ---------------------------------------------------------------------------
def test_status_runs_then_goes_idle_with_counts(file_db, libs, monkeypatch):
    from app.services import scan_status

    _make_movies(libs["movies"], 30)
    mid = {}

    def hook(n):
        if n == 28:
            with file_db() as other:
                mid["status"] = scan_status.read(other)

    _fake_probe(monkeypatch, hook)
    scheduler._run_folder_scan()

    running = mid["status"]
    assert running["state"] == "running"
    assert running["current_library"] == "movies"
    assert running["libraries"]["movies"]["state"] == "running"
    assert running["libraries"]["movies"]["seen"] >= 25
    assert running["started_at"]

    with file_db() as db:
        final = scan_status.read(db)
    assert final["state"] == "idle"
    assert final["current_library"] is None
    assert final["finished_at"] and final["started_at"]
    assert final["last_error"] is None
    movies = final["libraries"]["movies"]
    assert movies["state"] == "done"
    assert (movies["seen"], movies["added"], movies["probed"], movies["missing"], movies["errors"]) == (30, 30, 30, 0, 0)


def test_one_bad_music_file_does_not_stop_the_others(file_db, libs, monkeypatch):
    from sqlalchemy.exc import DataError

    from app.models.music import Track
    from app.services import scan_status

    # Three artists, one track each. The middle one fails the way the real bug
    # did: a tag value too long for its column (a SQLAlchemy DataError whose dump
    # carries "INSERT INTO" and the SQLAlchemy name). The scan must skip only
    # that file, keep the other two, and end "done with an error", not "failed".
    for name in ("Aretha", "Bob", "Cher"):
        _touch(libs["music"] / name / "Album" / "01 - Song.flac")

    def tags(path):
        name = Path(path).parts[-3]
        return {"albumartist": name, "album": "Album", "title": "Song", "tracknumber": "1"}

    monkeypatch.setattr(scan_library, "read_tags", tags)
    _fake_probe(monkeypatch)

    real_upsert = scan_library._upsert_file
    bad_path_part = os.path.join("Bob", "Album")

    def flaky_upsert(db, **kw):
        if bad_path_part in kw.get("path", ""):
            raise DataError(
                "INSERT INTO artists (id, name, mbid) VALUES (?, ?, ?)",
                {"mbid": "x" * 73},
                Exception("value too long for type character varying(64)"),
            )
        return real_upsert(db, **kw)

    monkeypatch.setattr(scan_library, "_upsert_file", flaky_upsert)

    scheduler._run_folder_scan()

    # Two tracks survived; the scan did not die on the first failure.
    assert _count(file_db, Track) == 2
    names = {a.name for a in _all(file_db, Artist)}
    assert "Aretha" in names and "Cher" in names
    assert "Bob" not in names, "the failed file's artist was rolled back"

    with file_db() as db:
        status = scan_status.read(db)
    music = status["libraries"]["music"]
    assert status["state"] == "idle"
    assert music["state"] == "done", "a skipped file is an error count, not a failed library"
    assert music["errors"] >= 1
    # The admin-facing error names the file and a short reason, not the SQL dump.
    last = status["last_error"] or ""
    assert bad_path_part in last
    assert "value too long" in last
    for leak in ("sqlalchemy", "INSERT INTO", "StringDataRightTruncation", "[SQL:"):
        assert leak not in last, f"raw SQL leaked into the admin status: {leak!r}"


def test_status_records_a_failed_library(file_db, libs, monkeypatch):
    from app.services import scan_status

    _make_movies(libs["movies"], 3)

    def hook(n):
        if n == 2:
            raise RuntimeError("share went away")

    _fake_probe(monkeypatch, hook)
    scheduler._run_folder_scan()
    with file_db() as db:
        final = scan_status.read(db)
    assert final["state"] == "idle"
    assert final["libraries"]["movies"]["state"] == "failed"
    assert "share went away" in (final["last_error"] or "")


def test_a_stale_running_status_becomes_idle_on_startup(db_session):
    from app.services import app_settings, scan_status

    app_settings.put(db_session, scan_status.KEY, {
        "state": "running", "started_at": "2026-10-08T10:00:00+00:00", "finished_at": None,
        "current_library": "movies", "libraries": {"movies": {"state": "running", "seen": 5}},
        "last_error": None,
    })
    db_session.commit()

    assert scan_status.reset_stale(db_session) is True
    db_session.commit()
    after = scan_status.read(db_session)
    assert after["state"] == "idle"
    assert after["current_library"] is None
    assert "interrupted" in after["last_error"]
    assert after["libraries"]["movies"]["state"] != "running"
    assert scan_status.reset_stale(db_session) is False


def test_api_startup_resets_a_stale_status():
    import inspect

    from app import main

    assert "scan_status.reset_stale" in inspect.getsource(main.lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@pytest.fixture()
def authed(db_session):
    """Real bearer tokens through the real dependencies; only the DB is swapped."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app
    from app.models.user import User
    from app.services.security import create_access_token
    from tests.conftest import make_active_session

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    admin = User(username="adm", display_name="Adm", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.flush()
    _, admin_sess = make_active_session(db_session, user=admin)
    member, member_sess = make_active_session(db_session)

    def headers(user, sess):
        return {"Authorization": "Bearer " + create_access_token(user.id, user.role, sess.id)}

    c = TestClient(app)
    try:
        yield c, headers(admin, admin_sess), headers(member, member_sess)
    finally:
        c.close()
        app.dependency_overrides.clear()


def test_scan_endpoints_are_admin_only(authed):
    client, admin_h, member_h = authed
    assert client.get("/api/admin/library/scan").status_code == 401
    assert client.post("/api/admin/library/scan").status_code == 401
    assert client.get("/api/admin/library/scan", headers=member_h).status_code == 403
    assert client.post("/api/admin/library/scan", headers=member_h).status_code == 403
    r = client.get("/api/admin/library/scan", headers=admin_h)
    assert r.status_code == 200
    assert r.json()["state"] == "idle"
    assert r.json()["libraries"] == {}


def test_post_scan_starts_one_and_answers_409_while_it_runs(authed, monkeypatch):
    client, admin_h, _member_h = authed
    triggered = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda: triggered.append(True))

    first = client.post("/api/admin/library/scan", headers=admin_h)
    assert first.status_code in (200, 202)
    assert first.json()["state"] == "running"
    assert triggered == [True]

    second = client.post("/api/admin/library/scan", headers=admin_h)
    assert second.status_code == 409
    assert triggered == [True], "a running scan must not be started twice"
    assert client.get("/api/admin/library/scan", headers=admin_h).json()["state"] == "running"


def test_scan_state_needs_sign_in_and_returns_only_running_and_finished_at(authed, db_session):
    from app.services import app_settings, scan_status

    client, admin_h, member_h = authed
    assert client.get("/api/library/scan-state").status_code == 401

    r = client.get("/api/library/scan-state", headers=member_h)
    assert r.status_code == 200
    assert r.json() == {"running": False, "finished_at": None}

    app_settings.put(db_session, scan_status.KEY, {
        "state": "running", "started_at": "2026-10-08T10:00:00+00:00", "finished_at": "2026-10-07T10:00:00+00:00",
        "current_library": "movies", "libraries": {"movies": {"state": "running"}}, "last_error": "secret detail",
    })
    db_session.commit()
    r = client.get("/api/library/scan-state", headers=member_h)
    assert set(r.json()) == {"running", "finished_at"}
    assert r.json()["running"] is True
    assert r.json()["finished_at"] == "2026-10-07T10:00:00+00:00"


def test_features_reports_which_arr_apps_are_configured(client, monkeypatch):
    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key"):
        monkeypatch.setattr(settings, key, "")
    assert client.get("/api/client/features").json()["arr"] == {"radarr": False, "sonarr": False, "lidarr": False}
    monkeypatch.setattr(settings, "sonarr_api_key", "abc")
    assert client.get("/api/client/features").json()["arr"] == {"radarr": False, "sonarr": True, "lidarr": False}
