"""Admin organizer API tests.

Covers all endpoints on /api/admin/library/organizer/...
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.library import Library, LibraryFolder, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.organizer import OrganizerJournal, OrganizerJournalItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lib(db, kind="movies"):
    lib = Library(id=uuid.uuid4(), kind=LibraryKind(kind), name=kind.title())
    db.add(lib)
    db.flush()
    return lib


def _lib_folder(db, library_id, path):
    lf = LibraryFolder(id=uuid.uuid4(), library_id=library_id, path=path)
    db.add(lf)
    db.flush()
    return lf


def _movie(db):
    m = Movie(id=uuid.uuid4(), title="Film", year=2022)
    db.add(m)
    db.flush()
    return m


def _mf(db, library_id, path, kind=MediaKind.movie, ref_id=None):
    mf = MediaFile(
        id=uuid.uuid4(), library_id=library_id, path=path,
        kind=kind, scan_state=ScanState.ready, ref_id=ref_id,
    )
    db.add(mf)
    db.flush()
    return mf


def _journal(db, library_id, state="preview"):
    j = OrganizerJournal(
        id=uuid.uuid4(), library_id=library_id, state=state,
        started_at=datetime.now(timezone.utc), item_count=0,
    )
    db.add(j)
    db.flush()
    return j


def _item(db, journal_id, mf_id, old_path, new_path=None, kind="rename"):
    it = OrganizerJournalItem(
        id=uuid.uuid4(), journal_id=journal_id, media_file_id=mf_id,
        item_kind=kind, old_path=old_path, new_path=new_path, sort_order=0,
    )
    db.add(it)
    db.flush()
    return it


# ---------------------------------------------------------------------------
# GET /{library_id}/settings
# ---------------------------------------------------------------------------

def test_get_settings_returns_200(client, db_session):
    lib = _lib(db_session)
    db_session.commit()
    r = client.get(f"/api/admin/library/organizer/{lib.id}/settings")
    assert r.status_code == 200
    body = r.json()
    assert "flip_flop_warnings" in body
    assert "presets" in body
    assert "ownership" in body


def test_get_settings_404_for_unknown_library(client, db_session):
    r = client.get(f"/api/admin/library/organizer/{uuid.uuid4()}/settings")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /{library_id}/settings
# ---------------------------------------------------------------------------

def test_put_settings_returns_200_with_flip_flop_warnings(client, db_session):
    lib = _lib(db_session)
    db_session.commit()
    r = client.put(
        f"/api/admin/library/organizer/{lib.id}/settings",
        json={"ownership": "f7five0"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "flip_flop_warnings" in body
    assert isinstance(body["flip_flop_warnings"], list)


def test_put_settings_returns_flip_flop_warnings_non_empty_when_stubbed(client, db_session):
    """Saving ownership=f7five0 on an arr-managed library returns non-empty warnings when
    check_flipflop returns a non-empty list (stubbed)."""
    lib = _lib(db_session)
    db_session.commit()
    with patch(
        "app.api.admin_organizer.check_flipflop",
        return_value=["Radarr has Rename Movies enabled"],
    ):
        r = client.put(
            f"/api/admin/library/organizer/{lib.id}/settings",
            json={"ownership": "f7five0"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "flip_flop_warnings" in body
    assert len(body["flip_flop_warnings"]) > 0
    assert body["flip_flop_warnings"][0] == "Radarr has Rename Movies enabled"


def test_put_settings_saves_naming_template(client, db_session):
    lib = _lib(db_session)
    db_session.commit()
    tpl = {"movie": "{Title} ({Year})/{Title} ({Year})"}
    r = client.put(
        f"/api/admin/library/organizer/{lib.id}/settings",
        json={"naming_template": tpl},
    )
    assert r.status_code == 200

    # Verify persisted
    r2 = client.get(f"/api/admin/library/organizer/{lib.id}/settings")
    assert r2.status_code == 200
    body = r2.json()
    assert body.get("naming_template", {}).get("movie") == tpl["movie"]


def test_put_settings_404_for_unknown_library(client, db_session):
    r = client.put(
        f"/api/admin/library/organizer/{uuid.uuid4()}/settings",
        json={"ownership": "arr"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /journals
# ---------------------------------------------------------------------------

def test_list_journals_empty(client, db_session):
    r = client.get("/api/admin/library/organizer/journals")
    assert r.status_code == 200
    assert r.json() == []


def test_list_journals_returns_items(client, db_session):
    lib = _lib(db_session)
    j1 = _journal(db_session, lib.id, "preview")
    j2 = _journal(db_session, lib.id, "done")
    db_session.commit()

    r = client.get("/api/admin/library/organizer/journals")
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert str(j1.id) in ids
    assert str(j2.id) in ids


def test_list_journals_filter_by_library_id(client, db_session):
    lib1 = _lib(db_session, "movies")
    lib2 = _lib(db_session, "tv")
    j1 = _journal(db_session, lib1.id)
    j2 = _journal(db_session, lib2.id)
    db_session.commit()

    r = client.get(f"/api/admin/library/organizer/journals?library_id={lib1.id}")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert str(j1.id) in ids
    assert str(j2.id) not in ids


# ---------------------------------------------------------------------------
# GET /journals/{journal_id}
# ---------------------------------------------------------------------------

def test_get_journal_returns_items(client, db_session, tmp_path):
    lib = _lib(db_session)
    movie = _movie(db_session)
    p = str(tmp_path / "old.mkv")
    mf = _mf(db_session, lib.id, p, ref_id=movie.id)
    j = _journal(db_session, lib.id)
    it = _item(db_session, j.id, mf.id, p, str(tmp_path / "new.mkv"))
    j.item_count = 1
    db_session.commit()

    r = client.get(f"/api/admin/library/organizer/journals/{j.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(j.id)
    assert len(body["items"]) == 1
    assert body["items"][0]["item_kind"] == "rename"


def test_get_journal_404_for_unknown(client, db_session):
    r = client.get(f"/api/admin/library/organizer/journals/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{library_id}/apply/{journal_id}
# ---------------------------------------------------------------------------

def test_apply_journal_queues_when_preview(client, db_session):
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "preview")
    db_session.commit()

    with patch("app.services.organizer.is_organizer_running", return_value=False), \
         patch("app.services.scan_status.is_running", return_value=False), \
         patch("app.services.scan_status.arr_is_running", return_value=False), \
         patch("app.scheduler.trigger_organizer_apply") as mock_apply:
        r = client.post(f"/api/admin/library/organizer/{lib.id}/apply/{j.id}")

    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    mock_apply.assert_called_once()


def test_apply_journal_409_when_not_preview(client, db_session):
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "done")
    db_session.commit()

    with patch("app.services.organizer.is_organizer_running", return_value=False), \
         patch("app.services.scan_status.is_running", return_value=False), \
         patch("app.services.scan_status.arr_is_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/apply/{j.id}")

    assert r.status_code == 409
    assert r.json()["detail"] == "journal_not_preview"


def test_apply_journal_409_when_organizer_running(client, db_session):
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "preview")
    db_session.commit()

    with patch("app.services.organizer.is_organizer_running", return_value=True), \
         patch("app.services.scan_status.is_running", return_value=False), \
         patch("app.services.scan_status.arr_is_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/apply/{j.id}")

    assert r.status_code == 409
    assert r.json()["detail"] == "organizer_already_running"


def test_apply_journal_404_for_unknown_journal(client, db_session):
    lib = _lib(db_session)
    db_session.commit()
    r = client.post(f"/api/admin/library/organizer/{lib.id}/apply/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{library_id}/undo/{journal_id}
# ---------------------------------------------------------------------------

def test_undo_journal_queues_when_done(client, db_session):
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "done")
    db_session.commit()

    with patch("app.services.organizer.is_organizer_running", return_value=False), \
         patch("app.services.scan_status.is_running", return_value=False), \
         patch("app.services.scan_status.arr_is_running", return_value=False), \
         patch("app.scheduler.trigger_organizer_undo") as mock_undo:
        r = client.post(f"/api/admin/library/organizer/{lib.id}/undo/{j.id}")

    assert r.status_code == 202
    mock_undo.assert_called_once()


def test_undo_journal_409_when_not_done(client, db_session):
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "preview")
    db_session.commit()

    with patch("app.services.organizer.is_organizer_running", return_value=False), \
         patch("app.services.scan_status.is_running", return_value=False), \
         patch("app.services.scan_status.arr_is_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/undo/{j.id}")

    assert r.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /versions/{media_file_id}
# ---------------------------------------------------------------------------

def test_delete_version_moves_file_and_returns_recycle_path(client, db_session, tmp_path):
    """Deleting the only file of a movie sets item_deleted=True (movie row removed)."""
    lib = _lib(db_session)
    folder = str(tmp_path / "movies")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)

    movie = _movie(db_session)
    p = str(tmp_path / "movies" / "film.mkv")
    Path(p).write_text("bytes")
    mf = _mf(db_session, lib.id, p, ref_id=movie.id)
    db_session.commit()

    r = client.delete(f"/api/admin/library/organizer/versions/{mf.id}")
    assert r.status_code == 200
    body = r.json()
    assert "recycle_path" in body
    assert "item_deleted" in body
    assert body["item_deleted"] is True
    assert os.path.exists(body["recycle_path"])
    assert not Path(p).exists()


def test_delete_version_item_not_deleted_when_second_file_remains(client, db_session, tmp_path):
    """Deleting one of two files for the same movie sets item_deleted=False (movie row kept)."""
    lib = _lib(db_session)
    folder = str(tmp_path / "movies2")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)

    movie = _movie(db_session)
    p1 = str(tmp_path / "movies2" / "film_copy1.mkv")
    p2 = str(tmp_path / "movies2" / "film_copy2.mkv")
    Path(p1).write_text("bytes1")
    Path(p2).write_text("bytes2")
    mf1 = _mf(db_session, lib.id, p1, ref_id=movie.id)
    _mf(db_session, lib.id, p2, ref_id=movie.id)
    db_session.commit()

    r = client.delete(f"/api/admin/library/organizer/versions/{mf1.id}")
    assert r.status_code == 200
    body = r.json()
    assert "item_deleted" in body
    assert body["item_deleted"] is False
    assert not Path(p1).exists()


def test_delete_version_404_for_unknown_media_file(client, db_session):
    r = client.delete(f"/api/admin/library/organizer/versions/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{library_id}/recycle
# ---------------------------------------------------------------------------

def test_list_recycle_returns_empty_when_no_recycle_folder(client, db_session, tmp_path):
    lib = _lib(db_session)
    folder = str(tmp_path / "empty_lib")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)
    db_session.commit()

    r = client.get(f"/api/admin/library/organizer/{lib.id}/recycle")
    assert r.status_code == 200
    assert r.json() == []


def test_list_recycle_returns_files_in_recycle_folder(client, db_session, tmp_path):
    lib = _lib(db_session)
    folder = str(tmp_path / "lib")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)
    db_session.commit()

    # Create a file in the recycle directory
    recycle_dir = os.path.join(folder, ".f7five0-recycle")
    os.makedirs(recycle_dir)
    (Path(recycle_dir) / "20991231T000000_old.mkv").write_text("trash")

    r = client.get(f"/api/admin/library/organizer/{lib.id}/recycle")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["filename"] == "20991231T000000_old.mkv"


# ---------------------------------------------------------------------------
# DELETE /{library_id}/recycle
# ---------------------------------------------------------------------------

def test_empty_recycle_deletes_files(client, db_session, tmp_path):
    lib = _lib(db_session)
    folder = str(tmp_path / "lib")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)
    db_session.commit()

    recycle_dir = os.path.join(folder, ".f7five0-recycle")
    os.makedirs(recycle_dir)
    for i in range(3):
        (Path(recycle_dir) / f"file{i}.mkv").write_text("trash")

    r = client.delete(f"/api/admin/library/organizer/{lib.id}/recycle")
    assert r.status_code == 200
    assert r.json()["deleted"] == 3
    assert os.listdir(recycle_dir) == []


def test_empty_recycle_returns_zero_when_no_folder(client, db_session, tmp_path):
    lib = _lib(db_session)
    folder = str(tmp_path / "empty")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)
    db_session.commit()

    r = client.delete(f"/api/admin/library/organizer/{lib.id}/recycle")
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# GET /{library_id}/template-preview
# ---------------------------------------------------------------------------

def test_template_preview_returns_list(client, db_session, tmp_path):
    lib = _lib(db_session)
    folder = str(tmp_path / "movies")
    os.makedirs(folder)
    _lib_folder(db_session, lib.id, folder)

    movie = _movie(db_session)
    p = str(tmp_path / "movies" / "movie.mkv")
    Path(p).write_text("fake")
    _mf(db_session, lib.id, p, ref_id=movie.id)

    from app.services import library_settings
    library_settings.save_settings(db_session, lib.id, {
        "naming_template": {"movie": "{Title} ({Year})/{Title} ({Year})"},
    })
    db_session.commit()

    r = client.get(f"/api/admin/library/organizer/{lib.id}/template-preview")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    if items:
        assert "media_file_id" in items[0]
        assert "old_path" in items[0]


def test_template_preview_404_for_unknown_library(client, db_session):
    r = client.get(f"/api/admin/library/organizer/{uuid.uuid4()}/template-preview")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 409 scan_running (criterion 21)
# ---------------------------------------------------------------------------

def test_preview_409_when_scan_is_running(client, db_session):
    """POST /{library_id}/preview returns 409 scan_running when folder scan is active."""
    lib = _lib(db_session)
    db_session.commit()

    with patch("app.services.scan_status.is_running", return_value=True), \
         patch("app.services.scan_status.arr_is_running", return_value=False), \
         patch("app.services.organizer.is_organizer_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/preview")

    assert r.status_code == 409
    assert r.json()["detail"] == "scan_running"


def test_preview_409_when_arr_sync_is_running(client, db_session):
    """POST /{library_id}/preview returns 409 arr_sync_running when *arr sync is active."""
    lib = _lib(db_session)
    db_session.commit()

    with patch("app.services.scan_status.is_running", return_value=False), \
         patch("app.services.scan_status.arr_is_running", return_value=True), \
         patch("app.services.organizer.is_organizer_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/preview")

    assert r.status_code == 409
    assert r.json()["detail"] == "arr_sync_running"


def test_apply_409_when_scan_is_running(client, db_session):
    """POST /{library_id}/apply/{journal_id} returns 409 scan_running when folder scan is active."""
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "preview")
    db_session.commit()

    with patch("app.services.scan_status.is_running", return_value=True), \
         patch("app.services.scan_status.arr_is_running", return_value=False), \
         patch("app.services.organizer.is_organizer_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/apply/{j.id}")

    assert r.status_code == 409
    assert r.json()["detail"] == "scan_running"


def test_undo_409_when_scan_is_running(client, db_session):
    """POST /{library_id}/undo/{journal_id} returns 409 scan_running when folder scan is active."""
    lib = _lib(db_session)
    j = _journal(db_session, lib.id, "done")
    db_session.commit()

    with patch("app.services.scan_status.is_running", return_value=True), \
         patch("app.services.scan_status.arr_is_running", return_value=False), \
         patch("app.services.organizer.is_organizer_running", return_value=False):
        r = client.post(f"/api/admin/library/organizer/{lib.id}/undo/{j.id}")

    assert r.status_code == 409
    assert r.json()["detail"] == "scan_running"
