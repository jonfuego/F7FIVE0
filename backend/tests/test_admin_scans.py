"""Admin > Scans: the folder scan for one library at a time, and the *arr
sync's own status and per-app start.

The fixtures (`authed`, `file_db`, `libs`) and helpers come from
test_library_scan.py, which owns the folder-scan test setup.
"""
from __future__ import annotations

import pytest

from app import scheduler
from app.config import settings
from app.models.movie import Movie
from app.models.music import Track
from app.services import arr_settings, scan_library, scan_status, sync
from tests.test_library_scan import (  # noqa: F401  (fixtures are used by name)
    _count, _fake_probe, _make_movies, _touch, authed, file_db, libs,
)


@pytest.fixture(autouse=True)
def _clean_arr_cache():
    arr_settings.reset_cache()
    yield
    arr_settings.reset_cache()


def _no_arr(monkeypatch):
    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key"):
        monkeypatch.setattr(settings, key, "")
    arr_settings.reset_cache()


def _set_key(monkeypatch, app: str) -> None:
    monkeypatch.setattr(settings, f"{app}_api_key", "abc")
    arr_settings.reset_cache()


# ---------------------------------------------------------------------------
# Folder scan: one library at a time
# ---------------------------------------------------------------------------
def test_post_scan_for_music_starts_just_music_when_there_is_no_lidarr(authed, libs, monkeypatch):
    """Music is startable from Admin > Scans without Lidarr: the folder scan
    takes ?library=music and passes only that library on."""
    client, admin_h, _member_h = authed
    _no_arr(monkeypatch)
    triggered = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda only=None: triggered.append(only))

    r = client.post("/api/admin/library/scan?library=music", headers=admin_h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["state"] == "running" and body["scope"] == ["music"]
    assert triggered == [["music"]]
    assert body["folders"]["music"] == 1 and body["folders"]["movies"] == 1


def test_post_scan_without_a_library_still_scans_everything(authed, libs, monkeypatch):
    client, admin_h, _member_h = authed
    _no_arr(monkeypatch)
    calls = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda *a, **kw: calls.append((a, kw)))
    r = client.post("/api/admin/library/scan", headers=admin_h)
    assert r.status_code == 202 and r.json()["scope"] is None
    assert calls == [((), {})], "the old call shape is unchanged"


def test_post_scan_takes_several_libraries_in_a_fixed_order(authed, libs, monkeypatch):
    client, admin_h, _member_h = authed
    _no_arr(monkeypatch)
    triggered = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda only=None: triggered.append(only))
    r = client.post("/api/admin/library/scan?library=music&library=movies&library=music", headers=admin_h)
    assert r.status_code == 202
    assert triggered == [["movies", "music"]]


def test_post_scan_for_a_library_a_key_owns_is_refused(authed, libs, monkeypatch):
    """With a Lidarr key the Lidarr sync owns music: the folder scan must never
    write it, so asking for it is a 400 and nothing starts."""
    client, admin_h, _member_h = authed
    _no_arr(monkeypatch)
    _set_key(monkeypatch, "lidarr")
    triggered = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda only=None: triggered.append(only))

    r = client.post("/api/admin/library/scan?library=music", headers=admin_h)
    assert r.status_code == 400 and r.json()["detail"] == "library_not_scanned"
    assert triggered == []
    assert client.get("/api/admin/library/scan", headers=admin_h).json()["state"] == "idle"
    # Movies has no key, so it is still fine.
    assert client.post("/api/admin/library/scan?library=movies", headers=admin_h).status_code == 202


def test_post_scan_for_a_library_with_no_folder_or_an_unknown_one_is_a_400(authed, libs, monkeypatch):
    client, admin_h, _member_h = authed
    _no_arr(monkeypatch)
    monkeypatch.setattr(settings, "library_root_music", "")
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda only=None: None)
    r = client.post("/api/admin/library/scan?library=music", headers=admin_h)
    assert r.status_code == 400 and r.json()["detail"] == "library_not_scanned"
    r = client.post("/api/admin/library/scan?library=music_videos", headers=admin_h)
    assert r.status_code == 400 and r.json()["detail"] == "unknown_library"


def test_post_scan_for_one_library_is_409_while_a_scan_runs_and_admin_only(authed, libs, monkeypatch):
    client, admin_h, member_h = authed
    _no_arr(monkeypatch)
    triggered = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda only=None: triggered.append(only))
    assert client.post("/api/admin/library/scan?library=tv", headers=admin_h).status_code == 202
    assert client.post("/api/admin/library/scan?library=music", headers=admin_h).status_code == 409
    assert client.post("/api/admin/library/scan", headers=admin_h).status_code == 409
    assert triggered == [["tv"]]
    assert client.post("/api/admin/library/scan?library=tv", headers=member_h).status_code == 403
    assert client.post("/api/admin/library/scan?library=tv").status_code == 401


def test_a_music_only_scan_scans_music_keeps_other_results_and_skips_music_videos(file_db, libs, monkeypatch):
    _no_arr(monkeypatch)
    _make_movies(libs["movies"], 3)
    _touch(libs["music"] / "Cher" / "Believe" / "01 - Believe.flac")
    monkeypatch.setattr(scan_library, "read_tags", lambda path: {
        "albumartist": "Cher", "album": "Believe", "title": "Believe", "tracknumber": "1"})
    _fake_probe(monkeypatch)
    mv_root = libs["movies"].parent / "music_videos"
    mv_root.mkdir()
    monkeypatch.setattr(settings, "library_root_music_videos", str(mv_root))
    mv_runs = []
    monkeypatch.setattr(scheduler, "_run_music_videos_scan", lambda: mv_runs.append(True))

    scheduler._run_folder_scan()  # everything first: movies, music, then music videos
    assert mv_runs == [True]
    with file_db() as db:
        first = scan_status.read(db)
    assert first["libraries"]["movies"]["seen"] == 3 and first["libraries"]["music"]["state"] == "done"
    assert _count(file_db, Movie) == 3

    mv_runs.clear()
    scheduler._run_folder_scan(["music"])
    assert mv_runs == [], "a scan of named libraries leaves music videos to their own button"
    with file_db() as db:
        after = scan_status.read(db)
    assert after["state"] == "idle" and after["scope"] == ["music"]
    assert after["libraries"]["movies"] == first["libraries"]["movies"], "movies keep their last result"
    assert after["libraries"]["music"]["state"] == "done"
    assert _count(file_db, Track) == 1 and _count(file_db, Movie) == 3


def test_a_scan_of_one_library_does_not_walk_the_others(file_db, libs, monkeypatch):
    _no_arr(monkeypatch)
    _make_movies(libs["movies"], 4)
    calls = _fake_probe(monkeypatch)
    scheduler._run_folder_scan(["tv"])
    assert calls == [], "only the TV folder was walked, and it is empty"
    assert _count(file_db, Movie) == 0


# ---------------------------------------------------------------------------
# *arr sync: status and per-app start
# ---------------------------------------------------------------------------
def test_the_arr_sync_post_for_one_app_runs_only_that_app(authed, monkeypatch):
    client, admin_h, member_h = authed
    _no_arr(monkeypatch)
    _set_key(monkeypatch, "lidarr")
    queued = []
    monkeypatch.setattr(scheduler, "trigger_arr_sync_now", lambda apps: queued.append(apps))
    monkeypatch.setattr(scheduler, "trigger_full_sync_now", lambda: queued.append("full"))

    r = client.post("/api/sync/run?app=lidarr", headers=admin_h)
    assert r.status_code == 202, r.text
    assert queued == [["lidarr"]], "no full sync, no folder scan"
    assert r.json()["state"] == "running" and r.json()["apps"]["lidarr"]["state"] == "queued"

    assert client.post("/api/sync/run?app=lidarr", headers=admin_h).status_code == 409
    got = client.get("/api/admin/library/arr-sync", headers=admin_h).json()
    assert got["state"] == "running"
    assert got["configured"] == {"radarr": False, "sonarr": False, "lidarr": True}
    assert client.get("/api/admin/library/arr-sync", headers=member_h).status_code == 403
    assert client.post("/api/sync/run?app=lidarr", headers=member_h).status_code == 403


def test_the_arr_sync_post_refuses_an_app_with_no_key_or_an_unknown_one(authed, monkeypatch):
    client, admin_h, _member_h = authed
    _no_arr(monkeypatch)
    queued = []
    monkeypatch.setattr(scheduler, "trigger_arr_sync_now", lambda apps: queued.append(apps))
    r = client.post("/api/sync/run?app=radarr", headers=admin_h)
    assert r.status_code == 400 and r.json()["detail"] == "app_not_configured"
    r = client.post("/api/sync/run?app=plex", headers=admin_h)
    assert r.status_code == 400 and r.json()["detail"] == "unknown_app"
    assert queued == []


def test_the_arr_sync_post_with_no_app_is_the_old_full_sync(authed, monkeypatch):
    client, admin_h, _member_h = authed
    queued = []
    monkeypatch.setattr(scheduler, "trigger_full_sync_now", lambda: queued.append("full"))
    r = client.post("/api/sync/run", headers=admin_h)
    assert r.status_code == 202 and r.json() == {"status": "enqueued"}
    assert queued == ["full"]


def test_the_arr_sync_job_writes_running_per_app_then_idle(file_db, monkeypatch):
    """The job syncs only the apps asked for, records each app's state and count
    while it goes, and ends idle with a finished time."""
    _no_arr(monkeypatch)
    _set_key(monkeypatch, "radarr")
    _set_key(monkeypatch, "lidarr")
    seen_mid = {}

    def fake_lidarr(db, stats):
        with file_db() as other:
            seen_mid["status"] = scan_status.arr_read(other)
        stats.artists_upserted += 7

    def never(db, stats):
        raise AssertionError("radarr was not asked for")

    monkeypatch.setattr(sync, "_run_lidarr", fake_lidarr)
    monkeypatch.setattr(sync, "_run_radarr", never)

    scheduler._run_full_sync(["lidarr"])

    mid = seen_mid["status"]
    assert mid["state"] == "running" and mid["current_app"] == "lidarr"
    assert mid["apps"]["lidarr"]["state"] == "running"
    with file_db() as db:
        final = scan_status.arr_read(db)
    assert final["state"] == "idle" and final["finished_at"] and final["last_error"] is None
    assert {k: final["apps"]["lidarr"][k] for k in ("state", "synced", "errors")} == {
        "state": "done", "synced": 7, "errors": 0,
    }
    assert "radarr" not in final["apps"]


def test_the_arr_sync_job_records_a_failed_app_without_stopping_the_next(file_db, monkeypatch):
    _no_arr(monkeypatch)
    _set_key(monkeypatch, "radarr")
    _set_key(monkeypatch, "sonarr")

    def broken(db, stats):
        raise RuntimeError("radarr is down")

    def fine(db, stats):
        stats.series_upserted += 2

    monkeypatch.setattr(sync, "_run_radarr", broken)
    monkeypatch.setattr(sync, "_run_sonarr", fine)
    scheduler._run_full_sync()
    with file_db() as db:
        final = scan_status.arr_read(db)
    assert final["state"] == "idle"
    assert final["apps"]["radarr"]["state"] == "failed" and final["apps"]["radarr"]["errors"] == 1
    assert {k: final["apps"]["sonarr"][k] for k in ("state", "synced", "errors")} == {
        "state": "done", "synced": 2, "errors": 0,
    }
    assert "radarr is down" in (final["last_error"] or "")


def test_the_arr_sync_job_writes_nothing_when_no_app_has_a_key(file_db, monkeypatch):
    _no_arr(monkeypatch)
    scheduler._run_full_sync()
    with file_db() as db:
        assert scan_status.arr_read(db)["finished_at"] is None


def test_a_stale_running_arr_sync_status_becomes_idle_on_startup(db_session):
    from app.services import app_settings

    app_settings.put(db_session, scan_status.ARR_KEY, {
        "state": "running", "started_at": "2026-10-08T10:00:00+00:00", "finished_at": None,
        "current_app": "sonarr", "apps": {"sonarr": {"state": "running", "synced": 1, "errors": 0}},
        "last_error": None,
    })
    db_session.commit()
    assert scan_status.reset_stale(db_session) is True
    db_session.commit()
    after = scan_status.arr_read(db_session)
    assert after["state"] == "idle" and "interrupted" in after["last_error"]
    assert after["apps"]["sonarr"]["state"] == "interrupted"
    assert scan_status.reset_stale(db_session) is False
