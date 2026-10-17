"""Path mappings (Admin > Library folders): a drive letter the services cannot see
(`N:`) is mapped to a network path in Admin, with no .env edit and no restart.

Fixtures and helpers come from test_library_scan.py and test_arr_sync_progress.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import scheduler
from app.api import admin_path_mappings
from app.config import settings
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.playback import WatchHistory, WatchProgress
from app.services import arr_settings, path_map, path_mappings, sync
from tests.conftest import make_active_session
from tests.test_arr_sync_progress import FakeRadarr, _radarr, _radarr_key
from tests.test_library_scan import (  # noqa: F401  (fixtures are used by name)
    _count, _fake_probe, _touch, authed, file_db, libs,
)

UNC = r"\\nas\share"


@pytest.fixture(autouse=True)
def _fresh_mappings():
    path_map.invalidate()
    yield
    path_map.invalidate()


def _strict_roots(monkeypatch):
    # The test config allows the whole temp dir; hold paths to the library roots.
    monkeypatch.setattr(settings, "stream_unsafe_allow_any_path", False)
    monkeypatch.setattr(settings, "stream_allowed_roots", "")


def _n_drive_movie(i, name="x"):
    return {
        "id": i, "tmdbId": 2000 + i, "title": f"Movie {i}", "year": 2020, "hasFile": True,
        "movieFile": {"path": rf"N:\Movies\{name} ({i})\{name}.mkv", "size": 16},
    }


# ---------------------------------------------------------------------------
# B2.1: the N:\ path fails with no mapping and works with a saved one
# ---------------------------------------------------------------------------
def test_an_n_drive_path_is_refused_without_a_mapping_and_stored_with_one(file_db, libs, monkeypatch, tmp_path):
    _radarr_key(monkeypatch)
    _strict_roots(monkeypatch)
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)
    # The share, as the service sees it: the Movies library folder is on it.
    share = tmp_path / "share"
    movie = share / "Movies" / "X (2020)" / "X (2020).mkv"
    _touch(movie)
    monkeypatch.setattr(settings, "library_root_movies", str(share / "Movies"))
    FakeRadarr.movies = [{
        "id": 1, "tmdbId": 2001, "title": "X", "year": 2020, "hasFile": True,
        "movieFile": {"path": r"N:\Movies\X (2020)\X (2020).mkv", "size": 16},
    }]
    monkeypatch.setattr(sync, "RadarrClient", FakeRadarr)
    monkeypatch.setattr(sync, "schedule_pending_enrichment", lambda stats: None)
    _fake_probe(monkeypatch)

    # No mapping: the service cannot place the file inside a library folder.
    scheduler._run_full_sync(["radarr"])
    assert _radarr(file_db)["refused"] == 1
    assert _count(file_db, MediaFile) == 0

    # An admin adds the mapping. Nothing restarts, no .env changes.
    with file_db() as db:
        path_mappings.save(db, "N:", str(share))
        db.commit()

    scheduler._run_full_sync(["radarr"])
    entry = _radarr(file_db)
    assert entry["refused"] == 0 and entry["ready"] == 1
    with file_db() as db:
        mf = db.scalar(select(MediaFile))
    assert mf.path == str(share) + "\\Movies\\X (2020)\\X (2020).mkv"
    assert mf.scan_state == ScanState.ready


def test_the_mapping_is_the_one_the_stream_process_reads_too(file_db):
    """The API and the stream gateway are separate processes: each reloads the
    saved mappings on a timer, so a change reaches both."""
    with file_db() as db:
        path_mappings.save(db, "n:", UNC + r"\The Hive")
        db.commit()
    path_map._db_cache = None  # a process that has not read it yet
    with file_db() as db:
        assert path_map.translate(r"N:\Movies\a.mkv", db) == UNC + "\\The Hive\\Movies\\a.mkv"
        # The separators after the drive are kept as they came (an existing rule).
        assert path_map.translate(r"n:/Movies/a.mkv", db) == UNC + "\\The Hive\\Movies/a.mkv"


# ---------------------------------------------------------------------------
# B2.2: stored rows are rewritten in place, so watch history survives
# ---------------------------------------------------------------------------
def _watched(db, path):
    user = make_active_session(db)[0]
    mf = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(), path=path, scan_state=ScanState.missing)
    db.add(mf)
    db.flush()
    db.add(WatchProgress(user_id=user.id, media_file_id=mf.id, position_sec=1234, duration_sec=7000))
    db.add(WatchHistory(
        user_id=user.id, media_file_id=mf.id, started_at=datetime.now(timezone.utc), last_position_sec=1234,
    ))
    db.flush()
    return user, mf


def test_saving_a_mapping_rewrites_stored_paths_in_place_and_keeps_watch_history(db_session, monkeypatch):
    _strict_roots(monkeypatch)
    monkeypatch.setattr(settings, "library_root_movies", UNC + r"\Movies")
    user, mf = _watched(db_session, r"N:\Movies\X (2020)\x.mkv")
    row_id = mf.id

    result = path_mappings.save(db_session, "N:", UNC)
    db_session.commit()
    assert result == {"rewritten": 1, "merged": 0}
    again = db_session.get(MediaFile, row_id)
    assert again.path == UNC + r"\Movies\X (2020)\x.mkv"

    # A sync that now reports the same file finds that row, not a new one.
    sync._upsert_media_file(
        db_session, kind=MediaKind.movie, ref_id=mf.ref_id, path=r"N:\Movies\X (2020)\x.mkv",
        arr_file={"size": 5}, stats=sync.SyncStats(),
    )
    db_session.commit()
    rows = db_session.scalars(select(MediaFile)).all()
    assert [r.id for r in rows] == [row_id]
    progress = db_session.get(WatchProgress, (user.id, row_id))
    assert progress is not None and progress.position_sec == 1234
    assert db_session.scalar(select(WatchHistory).where(WatchHistory.media_file_id == row_id)) is not None


def test_a_row_that_already_exists_at_the_new_path_is_merged_and_history_wins(db_session, monkeypatch):
    _strict_roots(monkeypatch)
    user, old = _watched(db_session, r"N:\Movies\Y (2021)\y.mkv")
    twin = MediaFile(kind=MediaKind.movie, ref_id=old.ref_id, path=UNC + r"\Movies\Y (2021)\y.mkv",
                     scan_state=ScanState.ready)
    db_session.add(twin)
    db_session.flush()

    result = path_mappings.save(db_session, "N:", UNC)
    db_session.commit()

    assert result["merged"] == 1
    rows = db_session.scalars(select(MediaFile)).all()
    assert len(rows) == 1
    assert rows[0].path == UNC + r"\Movies\Y (2021)\y.mkv"
    assert db_session.get(WatchProgress, (user.id, rows[0].id)).position_sec == 1234


def test_history_on_both_rows_moves_to_the_synced_row(db_session, monkeypatch):
    _strict_roots(monkeypatch)
    user, old = _watched(db_session, r"N:\Movies\Z (2022)\z.mkv")
    other_user = make_active_session(db_session)[0]
    twin = MediaFile(kind=MediaKind.movie, ref_id=old.ref_id, path=UNC + r"\Movies\Z (2022)\z.mkv",
                     scan_state=ScanState.ready)
    db_session.add(twin)
    db_session.flush()
    db_session.add(WatchProgress(user_id=other_user.id, media_file_id=twin.id, position_sec=9))
    db_session.flush()

    path_mappings.save(db_session, "N:", UNC)
    db_session.commit()

    rows = db_session.scalars(select(MediaFile)).all()
    assert len(rows) == 1 and rows[0].id == twin.id
    assert db_session.get(WatchProgress, (other_user.id, twin.id)).position_sec == 9
    assert db_session.get(WatchProgress, (user.id, twin.id)).position_sec == 1234


# ---------------------------------------------------------------------------
# B2.3: PATH_REWRITE_RULES in .env keeps working
# ---------------------------------------------------------------------------
def test_env_rules_still_work_with_no_saved_mappings(db_session, monkeypatch):
    monkeypatch.setattr(settings, "path_rewrite_rules", r"N:=\\nas\media")
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)
    assert path_map.translate(r"N:\Movies\a.mkv", db_session) == r"\\nas\media\Movies\a.mkv"
    assert path_map.translate(r"n:\Movies\a.mkv") == r"\\nas\media\Movies\a.mkv"
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)


def test_a_saved_mapping_wins_over_the_env_rule_for_the_same_drive(db_session, monkeypatch):
    monkeypatch.setattr(settings, "path_rewrite_rules", r"N:=\\old\media;M:=\\nas\music")
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)
    path_mappings.save(db_session, "N:", r"\\new\media")
    assert path_map.translate(r"N:\a.mkv", db_session) == r"\\new\media\a.mkv"
    assert path_map.translate(r"M:\b.flac", db_session) == r"\\nas\music\b.flac"
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)


# ---------------------------------------------------------------------------
# B2.4: the admin endpoints
# ---------------------------------------------------------------------------
def test_list_create_and_delete_mappings(authed):
    client, admin_h, _member = authed
    assert client.get("/api/admin/path-mappings", headers=admin_h).json()["mappings"] == []

    r = client.post("/api/admin/path-mappings", headers=admin_h, json={"src": "n:", "dst": UNC + "\\The Hive\\"})
    assert r.status_code == 200, r.text
    assert r.json()["mappings"] == [{"src": "N:", "dst": UNC + r"\The Hive"}]

    # The same drive again changes its target instead of adding a second row.
    r = client.post("/api/admin/path-mappings", headers=admin_h, json={"src": "N:", "dst": UNC + "\\Other"})
    assert r.json()["mappings"] == [{"src": "N:", "dst": UNC + r"\Other"}]

    r = client.delete("/api/admin/path-mappings?src=N:", headers=admin_h)
    assert r.status_code == 200 and r.json()["mappings"] == []
    assert client.delete("/api/admin/path-mappings?src=N:", headers=admin_h).status_code == 404


@pytest.mark.parametrize("src,dst,code", [
    ("N", UNC, "bad_drive"),
    ("NN:", UNC, "bad_drive"),
    ("N:", "relative\\path", "bad_target"),
    ("N:", "\\\\onlyserver", "bad_target"),
    ("N:", "N:\\Movies", "loop"),
])
def test_a_bad_mapping_is_refused_with_a_reason(authed, src, dst, code):
    client, admin_h, _member = authed
    r = client.post("/api/admin/path-mappings", headers=admin_h, json={"src": src, "dst": dst})
    assert r.status_code == 422
    assert r.json()["detail"] == code
    assert client.get("/api/admin/path-mappings", headers=admin_h).json()["mappings"] == []


def test_a_member_cannot_read_or_change_mappings(authed):
    client, _admin, member_h = authed
    assert client.get("/api/admin/path-mappings", headers=member_h).status_code == 403
    assert client.post("/api/admin/path-mappings", headers=member_h, json={"src": "N:", "dst": UNC}).status_code == 403
    assert client.delete("/api/admin/path-mappings?src=N:", headers=member_h).status_code == 403
    assert client.get("/api/admin/path-mappings/arr-roots", headers=member_h).status_code == 403


def test_arr_roots_say_which_folders_the_service_can_open(authed, monkeypatch, tmp_path):
    client, admin_h, _member = authed
    _radarr_key(monkeypatch)
    here = tmp_path / "Movies"
    here.mkdir()

    class Fake:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def root_folders(self):
            return [{"path": r"N:\Movies"}, {"path": str(here)}, {"path": r"N:\Movies"}]

    monkeypatch.setitem(admin_path_mappings._CLIENTS, "radarr", Fake)
    # This PC may really have an N: in its own login; the service must not.
    real_isdir = path_mappings._is_dir
    monkeypatch.setattr(path_mappings, "_is_dir", lambda p: not p.upper().startswith("N:") and real_isdir(p))
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)

    body = client.get("/api/admin/path-mappings/arr-roots", headers=admin_h).json()
    assert body["errors"] == []
    by_path = {r["path"]: r for r in body["roots"]}
    assert len(body["roots"]) == 2, "a repeated root is listed once"
    assert by_path[r"N:\Movies"]["reachable"] is False
    assert by_path[r"N:\Movies"]["drive"] == "N:"
    assert by_path[r"N:\Movies"]["mapped"] is False
    assert by_path[str(here)]["reachable"] is True and by_path[str(here)]["drive"] is None

    # With a mapping the translated path is shown, and it is reachable.
    share = tmp_path / "share"
    (share / "Movies").mkdir(parents=True)
    client.post("/api/admin/path-mappings", headers=admin_h, json={"src": "N:", "dst": str(share)})
    body = client.get("/api/admin/path-mappings/arr-roots", headers=admin_h).json()
    mapped = {r["path"]: r for r in body["roots"]}[r"N:\Movies"]
    assert mapped["mapped"] is True and mapped["reachable"] is True
    assert mapped["translated"] == str(share) + "\\Movies" and mapped["drive"] is None


def test_an_arr_that_cannot_be_asked_is_a_note_not_a_failure(authed, monkeypatch):
    client, admin_h, _member = authed
    _radarr_key(monkeypatch)

    class Down:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def root_folders(self):
            raise RuntimeError("connection refused")

    monkeypatch.setitem(admin_path_mappings._CLIENTS, "radarr", Down)
    r = client.get("/api/admin/path-mappings/arr-roots", headers=admin_h)
    assert r.status_code == 200
    body = r.json()
    assert body["roots"] == [] and body["errors"][0]["app"] == "radarr"
    assert "connection refused" in body["errors"][0]["error"]


# ---------------------------------------------------------------------------
# B2.6 (backend half): the sync says which drive most missing files are on
# ---------------------------------------------------------------------------
def test_the_status_names_the_drive_most_missing_files_are_on(file_db, libs, monkeypatch):
    _radarr_key(monkeypatch)
    _strict_roots(monkeypatch)
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)
    monkeypatch.setattr(settings, "library_root_movies", r"N:\Movies")
    monkeypatch.setattr(sync, "_drive_visible", lambda drive: drive != "N:")
    FakeRadarr.movies = [_n_drive_movie(i) for i in range(1, 4)]
    monkeypatch.setattr(sync, "RadarrClient", FakeRadarr)
    monkeypatch.setattr(sync, "schedule_pending_enrichment", lambda stats: None)
    _fake_probe(monkeypatch)

    scheduler._run_full_sync(["radarr"])

    entry = _radarr(file_db)
    assert entry["missing"] == 3
    assert entry["missing_drive"] == "N:" and entry["missing_drive_count"] == 3


def test_a_drive_that_is_under_half_of_the_missing_files_is_not_named(file_db, libs, monkeypatch, tmp_path):
    _radarr_key(monkeypatch)
    _strict_roots(monkeypatch)
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(path_map, "_RULES_CACHE", None)
    monkeypatch.setattr(settings, "library_root_movies", str(tmp_path / "Movies"))
    gone_local = [
        {"id": i, "tmdbId": 3000 + i, "title": f"L{i}", "year": 2020, "hasFile": True,
         "movieFile": {"path": str(tmp_path / "Movies" / f"L{i}.mkv"), "size": 1}}
        for i in range(1, 4)
    ]
    FakeRadarr.movies = gone_local
    monkeypatch.setattr(sync, "RadarrClient", FakeRadarr)
    monkeypatch.setattr(sync, "schedule_pending_enrichment", lambda stats: None)
    _fake_probe(monkeypatch)
    scheduler._run_full_sync(["radarr"])
    entry = _radarr(file_db)
    assert entry["missing"] == 3
    assert "missing_drive" not in entry
