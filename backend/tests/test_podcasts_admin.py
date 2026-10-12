"""Admin podcasts: storage and the free-space reminder, Refresh feeds, and the
Podcasts row of the folder scan."""
from __future__ import annotations

import pytest

from app import scheduler
from app.config import settings
from app.services import reminders, scan_status
from app.services.podcasts import storage
from tests.podcast_helpers import Api, make_user


@pytest.fixture()
def api(db_session):
    a = Api(db_session)
    yield a
    a.close()


# ---------------------------------------------------------------------------
# Storage, free space reminder, refresh endpoints
# ---------------------------------------------------------------------------
def test_free_space_reminder_uses_the_threshold(db_session, tmp_path, monkeypatch):
    from app.services import library_folders
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    root = tmp_path / "pod"
    root.mkdir()
    library_folders.save(db_session, {"podcasts": [str(root)]})
    db_session.commit()
    gb = 1024 ** 3
    monkeypatch.setattr(settings, "podcast_free_space_warn_gb", 10)
    monkeypatch.setattr(storage, "disk_free", lambda path: (5 * gb, 100 * gb))
    r = next(x for x in reminders.REMINDERS if x.id == "podcast_space")
    assert r.applies(db_session) is True
    assert storage.usage(db_session)["low_space"] is True
    monkeypatch.setattr(storage, "disk_free", lambda path: (50 * gb, 100 * gb))
    assert r.applies(db_session) is False
    monkeypatch.setattr(settings, "podcast_free_space_warn_gb", 80)
    assert r.applies(db_session) is True
    assert settings.podcast_free_space_warn_gb == 80


def test_default_settings():
    from app.config import Settings
    fields = Settings.model_fields
    assert fields["podcast_refresh_minutes"].default == 60
    assert fields["podcast_free_space_warn_gb"].default == 10
    assert fields["podcastindex_api_key"].default == ""
    assert fields["podcastindex_api_secret"].default == ""


def test_no_podcasts_folder_means_no_space_warning(db_session):
    r = next(x for x in reminders.REMINDERS if x.id == "podcast_space")
    assert r.applies(db_session) is False


def test_storage_endpoint_sums_only_the_files_f7five0_downloaded(api, db_session, tmp_path, monkeypatch):
    from app.models.media_file import MediaFile, MediaKind, ScanState
    from app.services import library_folders
    from tests.podcast_helpers import make_episode, make_podcast
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    root = tmp_path / "pod"
    root.mkdir()
    library_folders.save(db_session, {"podcasts": [str(root)]})
    pod = make_podcast(db_session)
    mine = make_episode(db_session, pod)
    theirs = make_episode(db_session, pod)
    for ep, size, flag in ((mine, 1000, True), (theirs, 5000, False)):
        mf = MediaFile(kind=MediaKind.podcast_episode, ref_id=ep.id, path=str(root / f"{ep.id}.mp3"), size_bytes=size, scan_state=ScanState.ready)
        db_session.add(mf)
        db_session.flush()
        ep.media_file_id, ep.downloaded_by_f7five0 = mf.id, flag
    db_session.commit()
    gb = 1024 ** 3
    monkeypatch.setattr(storage, "disk_free", lambda path: (7 * gb, 100 * gb))
    admin = make_user(db_session, role="admin")
    body = api.as_user(admin).get("/api/admin/podcasts/storage").json()
    assert body["used_bytes"] == 1000
    assert body["warn_gb"] == 10 and body["low_space"] is True
    assert body["folders"] == [{"path": str(root), "reachable": True, "free_bytes": 7 * gb, "total_bytes": 100 * gb}]


def test_admin_refresh_feeds_starts_once_and_reports_status(api, db_session, monkeypatch):
    started: list = []
    monkeypatch.setattr(scheduler, "trigger_podcast_refresh_now", lambda ids=None: started.append(ids))
    admin = make_user(db_session, role="admin")
    c = api.as_user(admin)
    assert c.get("/api/admin/podcasts/refresh").json()["state"] == "idle"
    r = c.post("/api/admin/podcasts/refresh")
    assert r.status_code == 202 and r.json()["state"] == "running"
    assert started == [None]
    assert c.post("/api/admin/podcasts/refresh").status_code == 409
    assert scan_status.pr_read(db_session)["state"] == "running"


def test_folder_scan_endpoint_accepts_the_podcasts_library(api, db_session, tmp_path, monkeypatch):
    from app.services import library_folders
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    started: list = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda only=None: started.append(only))
    root = tmp_path / "pod"
    root.mkdir()
    library_folders.save(db_session, {"podcasts": [str(root)]})
    db_session.commit()
    admin = make_user(db_session, role="admin")
    c = api.as_user(admin)
    assert c.get("/api/admin/library/scan").json()["folders"]["podcasts"] == 1
    r = c.post("/api/admin/library/scan", params={"library": "podcasts"})
    assert r.status_code == 202, r.text
    assert started == [["podcasts"]]
    assert any(
        l["kind"] == "podcasts" and l["label"] == "Podcasts"
        for l in c.get("/api/admin/library-folders").json()["libraries"]
    )
