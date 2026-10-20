"""Round-trip: preview → apply → undo verifies the journal lifecycle end-to-end.

Uses tmp_path for real files. apply_run and undo_run open their own sessions
(StaticPool shares the single SQLite connection, so committed data is visible).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.library import Library, LibraryFolder, LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.organizer import OrganizerJournal
from app.models.user import User
from app.services import library_settings, organizer


def _setup_movie_library(db, tmp_path):
    """Create a library, folder, movie, and media file ready to rename."""
    u = User(
        id=uuid.uuid4(), username=f"u-{uuid.uuid4().hex[:8]}", display_name="T",
        password_hash="x", role="admin", is_active=True,
    )
    db.add(u)
    db.flush()

    lib = Library(id=uuid.uuid4(), kind=LibraryKind("movies"), name="Movies")
    db.add(lib)
    db.flush()

    folder = str(tmp_path / "movies")
    os.makedirs(folder, exist_ok=True)
    lf = LibraryFolder(id=uuid.uuid4(), library_id=lib.id, path=folder)
    db.add(lf)
    db.flush()

    movie = Movie(id=uuid.uuid4(), title="Round Trip", year=2023)
    db.add(movie)
    db.flush()

    # File with a name that will be different from the template rendering.
    src = Path(folder) / "old_name.mkv"
    src.write_text("fake video content")
    mf = MediaFile(
        id=uuid.uuid4(), library_id=lib.id, path=str(src),
        kind=MediaKind.movie, scan_state=ScanState.ready, ref_id=movie.id,
    )
    db.add(mf)
    db.flush()

    return u, lib, movie, mf, src


def test_preview_apply_undo_round_trip(db_session, tmp_path):
    """Full lifecycle: preview sees a rename, apply renames, undo restores."""
    u, lib, movie, mf, src = _setup_movie_library(db_session, tmp_path)

    library_settings.save_settings(db_session, lib.id, {
        "naming_template": {"movie": "{Title} ({Year})/{Title} ({Year})"},
    })
    db_session.commit()

    # ------- preview -------
    journal = organizer.preview(db_session, lib.id, u.id)
    assert journal.state == "preview"
    rename_items = [i for i in journal.items if i.item_kind in ("rename", "both")]
    assert len(rename_items) >= 1, "Expected at least one rename item"

    new_path = rename_items[0].new_path
    assert new_path is not None
    assert "Round Trip" in new_path

    db_session.commit()

    # ------- apply -------
    organizer.apply_run(journal.id, u.id)

    db_session.expire_all()
    j_after = db_session.get(OrganizerJournal, journal.id)
    assert j_after.state == "done", f"Expected done, got {j_after.state!r}"

    mf_after = db_session.get(MediaFile, mf.id)
    assert mf_after.path == new_path
    assert Path(new_path).exists()
    assert not src.exists()

    # ------- undo -------
    organizer.undo_run(journal.id, u.id)

    db_session.expire_all()
    j_undo = db_session.get(OrganizerJournal, journal.id)
    assert j_undo.state == "undone", f"Expected undone, got {j_undo.state!r}"

    mf_undo = db_session.get(MediaFile, mf.id)
    assert mf_undo.path == str(src)
    assert src.exists()
    assert not Path(new_path).exists()
