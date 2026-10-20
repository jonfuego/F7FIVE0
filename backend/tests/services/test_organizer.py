"""Tests for services/organizer.py (unit level, real filesystem via tmp_path)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.library import Library, LibraryFolder, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.organizer import OrganizerJournal, OrganizerJournalItem
from app.models.user import User
from app.services import organizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db) -> User:
    u = User(
        id=uuid.uuid4(),
        username=f"u-{uuid.uuid4().hex[:8]}",
        display_name="Test",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_library(db, kind: str = "movies") -> Library:
    lib = Library(id=uuid.uuid4(), kind=LibraryKind(kind), name=kind.title())
    db.add(lib)
    db.flush()
    return lib


def _make_lib_folder(db, library_id, path: str) -> LibraryFolder:
    lf = LibraryFolder(id=uuid.uuid4(), library_id=library_id, path=path)
    db.add(lf)
    db.flush()
    return lf


def _make_movie(db) -> Movie:
    m = Movie(id=uuid.uuid4(), title="Test Movie", year=2020)
    db.add(m)
    db.flush()
    return m


def _make_media_file(db, library_id, path: str, kind: MediaKind = MediaKind.movie,
                     ref_id=None) -> MediaFile:
    mf = MediaFile(
        id=uuid.uuid4(),
        library_id=library_id,
        path=path,
        kind=kind,
        scan_state=ScanState.ready,
        ref_id=ref_id,
    )
    db.add(mf)
    db.flush()
    return mf


def _make_journal(db, library_id, state: str = "preview") -> OrganizerJournal:
    j = OrganizerJournal(
        id=uuid.uuid4(),
        library_id=library_id,
        state=state,
        started_at=datetime.now(timezone.utc),
        item_count=0,
    )
    db.add(j)
    db.flush()
    return j


def _make_item(db, journal_id, mf_id, old_path: str, new_path: str,
               item_kind: str = "rename", sort_order: int = 0) -> OrganizerJournalItem:
    item = OrganizerJournalItem(
        id=uuid.uuid4(),
        journal_id=journal_id,
        media_file_id=mf_id,
        item_kind=item_kind,
        old_path=old_path,
        new_path=new_path,
        sort_order=sort_order,
    )
    db.add(item)
    db.flush()
    return item


# ---------------------------------------------------------------------------
# is_organizer_running
# ---------------------------------------------------------------------------

def test_is_organizer_running_false_when_lock_free():
    assert organizer.is_organizer_running() is False


def test_is_organizer_running_true_when_lock_held():
    organizer._organizer_lock.acquire()
    try:
        assert organizer.is_organizer_running() is True
    finally:
        organizer._organizer_lock.release()


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

def test_preview_does_not_call_os_rename(db_session, tmp_path, monkeypatch):
    """preview must not touch the filesystem."""
    def _bad_rename(*_a, **_kw):
        raise AssertionError("os.rename must not be called during preview")

    monkeypatch.setattr(os, "rename", _bad_rename)

    user = _make_user(db_session)
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie = _make_movie(db_session)
    real_file = tmp_path / "movies" / "Test Movie (2020).mkv"
    real_file.write_text("fake")
    _make_media_file(db_session, lib.id, str(real_file), MediaKind.movie, movie.id)
    db_session.commit()

    from app.services import library_settings
    library_settings.save_settings(db_session, lib.id, {
        "naming_template": {"movie": "{Title} ({Year})/{Title} ({Year})"},
    })
    db_session.commit()

    journal = organizer.preview(db_session, lib.id, user.id)
    assert journal is not None
    assert journal.id is not None


def test_preview_creates_journal_and_item_for_rename(db_session, tmp_path):
    user = _make_user(db_session)
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie = _make_movie(db_session)
    old_file = tmp_path / "movies" / "old_name.mkv"
    old_file.write_text("fake")
    _make_media_file(db_session, lib.id, str(old_file), MediaKind.movie, movie.id)

    from app.services import library_settings
    library_settings.save_settings(db_session, lib.id, {
        "naming_template": {"movie": "New Name ({Year})"},
    })
    db_session.commit()

    journal = organizer.preview(db_session, lib.id, user.id)
    assert journal.state == "preview"
    items = [i for i in journal.items if i.item_kind in ("rename", "both")]
    assert len(items) >= 1


# ---------------------------------------------------------------------------
# apply_run: calls apply_run which opens its own SessionLocal() internally
# ---------------------------------------------------------------------------

def test_apply_run_calls_os_rename_and_updates_path(db_session, tmp_path):
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie = _make_movie(db_session)
    old_file = tmp_path / "movies" / "old.mkv"
    old_file.write_text("content")
    mf = _make_media_file(db_session, lib.id, str(old_file), MediaKind.movie, movie.id)

    new_path = str(tmp_path / "movies" / "new.mkv")

    journal = _make_journal(db_session, lib.id, "preview")
    item = _make_item(db_session, journal.id, mf.id, str(old_file), new_path)
    journal.item_count = 1
    db_session.commit()

    organizer.apply_run(journal.id, uuid.uuid4())

    db_session.expire_all()
    updated_mf = db_session.get(MediaFile, mf.id)
    assert updated_mf.path == new_path
    assert Path(new_path).exists()
    assert not old_file.exists()


def test_apply_run_records_source_not_found_and_continues(db_session, tmp_path):
    """An OSError on one item (missing source) is recorded; remaining items still run."""
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie1 = _make_movie(db_session)
    movie2 = Movie(id=uuid.uuid4(), title="Movie 2", year=2021)
    db_session.add(movie2)
    db_session.flush()

    file1 = tmp_path / "movies" / "file1.mkv"
    file1.write_text("content1")
    file2 = tmp_path / "movies" / "file2.mkv"
    file2.write_text("content2")

    mf1 = _make_media_file(db_session, lib.id, str(file1), MediaKind.movie, movie1.id)
    mf2 = _make_media_file(db_session, lib.id, str(file2), MediaKind.movie, movie2.id)

    new1 = str(tmp_path / "movies" / "new1.mkv")
    new2 = str(tmp_path / "movies" / "new2.mkv")

    journal = _make_journal(db_session, lib.id, "preview")
    # item1 has valid source
    _make_item(db_session, journal.id, mf1.id, str(file1), new1, sort_order=0)
    # item2 has nonexistent source
    _make_item(db_session, journal.id, mf2.id, "/nonexistent/missing.mkv", new2, sort_order=1)
    journal.item_count = 2
    db_session.commit()

    organizer.apply_run(journal.id, uuid.uuid4())

    db_session.expire_all()
    # item1 succeeded: file moved
    assert Path(new1).exists()
    # item2 failed: error recorded
    items = db_session.scalars(
        __import__("sqlalchemy", fromlist=["select"]).select(OrganizerJournalItem)
        .where(OrganizerJournalItem.journal_id == journal.id)
        .order_by(OrganizerJournalItem.sort_order)
    ).all()
    item2_db = items[1]
    assert item2_db.error is not None
    # Journal state is "done" (not "failed") because at least one item succeeded
    j_db = db_session.get(OrganizerJournal, journal.id)
    assert j_db.state == "done"


# ---------------------------------------------------------------------------
# undo_run
# ---------------------------------------------------------------------------

def test_undo_run_renames_back_and_restores_path(db_session, tmp_path):
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie = _make_movie(db_session)
    original_path = str(tmp_path / "movies" / "original.mkv")
    applied_path = str(tmp_path / "movies" / "applied.mkv")
    Path(applied_path).write_text("content")

    mf = _make_media_file(db_session, lib.id, applied_path, MediaKind.movie, movie.id)

    journal = _make_journal(db_session, lib.id, "done")
    item = _make_item(db_session, journal.id, mf.id, original_path, applied_path)
    journal.item_count = 1
    db_session.commit()

    organizer.undo_run(journal.id, uuid.uuid4())

    db_session.expire_all()
    assert Path(original_path).exists()
    assert not Path(applied_path).exists()
    mf_db = db_session.get(MediaFile, mf.id)
    assert mf_db.path == original_path
    j_db = db_session.get(OrganizerJournal, journal.id)
    assert j_db.state == "undone"


# ---------------------------------------------------------------------------
# move_to_recycle
# ---------------------------------------------------------------------------

def test_move_to_recycle_moves_file_and_deletes_row(db_session, tmp_path):
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie = _make_movie(db_session)
    media_file = tmp_path / "movies" / "the_movie.mkv"
    media_file.write_text("content")
    mf = _make_media_file(db_session, lib.id, str(media_file), MediaKind.movie, movie.id)
    db_session.commit()

    recycle_path, item_deleted = organizer.move_to_recycle(db_session, mf.id, lib.id)
    db_session.commit()

    assert os.path.exists(recycle_path)
    assert not media_file.exists()
    assert db_session.get(MediaFile, mf.id) is None
    assert item_deleted is True
    assert db_session.get(Movie, movie.id) is None


def test_move_to_recycle_item_not_deleted_when_other_file_exists(db_session, tmp_path):
    lib = _make_library(db_session, "movies")
    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    _make_lib_folder(db_session, lib.id, folder)

    movie = _make_movie(db_session)
    file1 = tmp_path / "movies" / "copy1.mkv"
    file1.write_text("content1")
    file2 = tmp_path / "movies" / "copy2.mkv"
    file2.write_text("content2")
    mf1 = _make_media_file(db_session, lib.id, str(file1), MediaKind.movie, movie.id)
    _make_media_file(db_session, lib.id, str(file2), MediaKind.movie, movie.id)
    db_session.commit()

    _, item_deleted = organizer.move_to_recycle(db_session, mf1.id, lib.id)
    db_session.commit()

    assert item_deleted is False
    assert db_session.get(Movie, movie.id) is not None


# ---------------------------------------------------------------------------
# Safety: escape-folder prevention (AC 18)
# ---------------------------------------------------------------------------

def test_is_contained_rejects_outside_path(tmp_path):
    """_is_contained must return False when the path escapes the folder."""
    from app.services.organizer import _is_contained
    folder = str(tmp_path / "movies")
    assert not _is_contained(str(tmp_path / "other" / "film.mkv"), folder)
    assert not _is_contained(str(tmp_path / "film.mkv"), folder)
    assert _is_contained(str(tmp_path / "movies" / "film.mkv"), folder)
    assert _is_contained(str(tmp_path / "movies" / "sub" / "film.mkv"), folder)


def test_compute_new_path_returns_none_for_escape(tmp_path):
    """_compute_new_path returns None when the normpath falls outside the folder."""
    from app.services.organizer import _compute_new_path
    folder = str(tmp_path / "movies")
    os.makedirs(folder)

    # Build a fake MediaFile (not persisted) whose path is inside the folder
    mf = MediaFile(
        id=uuid.uuid4(),
        path=str(tmp_path / "movies" / "movie.mkv"),
        kind=MediaKind.movie,
        scan_state=ScanState.ready,
    )
    tokens = {"Title": "Test", "Year": "2020"}

    # A normal template renders inside the folder
    result_ok = _compute_new_path(mf, tokens, "{Title} ({Year})", folder)
    assert result_ok is not None

    # A template whose raw render would escape -- safe_segment turns ".." into "_"
    # so the only genuine escape is a pre-built absolute path.  We verify the guard
    # by injecting a token whose value contains a traversal after safe_segment
    # produces an outside path.  The simplest proof: if render_safe somehow returned
    # an absolute path, normpath would keep it outside the folder.
    # Patch render_safe inside _compute_new_path to simulate that scenario.
    from app.services import naming_templates as nt_mod
    original_render_safe = nt_mod.render_safe

    def _escape_render_safe(template, tokens_):
        # Return a relative path that, when joined with folder, escapes via normpath
        # e.g. "../../escape/film" to simulate a hypothetical render_safe bypass
        return "../../escape/film"

    import app.services.naming_templates as nt
    original = nt.render_safe
    nt.render_safe = _escape_render_safe
    try:
        result_bad = _compute_new_path(mf, tokens, "{Title}", folder)
    finally:
        nt.render_safe = original

    assert result_bad is None, "Path escaping the folder must be rejected by _compute_new_path"
