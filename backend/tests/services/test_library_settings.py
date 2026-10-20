"""Tests for services/library_settings.py."""
from __future__ import annotations

import json
import uuid

import pytest

from app.models.library import Library, LibraryKind
from app.services import library_settings
from app.services.library_folders import arr_managed


def _make_library(db, kind: str, settings_json: str | None = None) -> Library:
    lib = Library(
        id=uuid.uuid4(),
        kind=LibraryKind(kind),
        name=kind.title(),
        settings=settings_json,
    )
    db.add(lib)
    db.flush()
    return lib


# ---------------------------------------------------------------------------
# get_ownership defaults
# ---------------------------------------------------------------------------

def test_get_ownership_returns_arr_for_arr_managed_library_with_no_settings(db_session, monkeypatch):
    monkeypatch.setattr("app.services.library_settings.arr_managed", lambda _kind: True)
    lib = _make_library(db_session, "movies")
    result = library_settings.get_ownership(db_session, lib.id)
    assert result == "arr"


def test_get_ownership_returns_f7five0_for_non_arr_library_with_no_settings(db_session, monkeypatch):
    monkeypatch.setattr("app.services.library_settings.arr_managed", lambda _kind: False)
    lib = _make_library(db_session, "music")
    result = library_settings.get_ownership(db_session, lib.id)
    assert result == "f7five0"


def test_get_ownership_returns_saved_value(db_session, monkeypatch):
    monkeypatch.setattr("app.services.library_settings.arr_managed", lambda _kind: True)
    lib = _make_library(db_session, "movies", json.dumps({"ownership": "f7five0"}))
    result = library_settings.get_ownership(db_session, lib.id)
    assert result == "f7five0"


def test_get_ownership_saved_arr_overrides_non_arr_default(db_session, monkeypatch):
    monkeypatch.setattr("app.services.library_settings.arr_managed", lambda _kind: False)
    lib = _make_library(db_session, "music", json.dumps({"ownership": "arr"}))
    result = library_settings.get_ownership(db_session, lib.id)
    assert result == "arr"


# ---------------------------------------------------------------------------
# save_settings round-trip
# ---------------------------------------------------------------------------

def test_save_settings_round_trips_ownership(db_session):
    lib = _make_library(db_session, "movies")
    library_settings.save_settings(db_session, lib.id, {"ownership": "f7five0"})
    db_session.commit()

    saved = json.loads(db_session.get(Library, lib.id).settings or "{}")
    assert saved["ownership"] == "f7five0"


def test_save_settings_round_trips_naming_template(db_session):
    lib = _make_library(db_session, "music")
    tpl = {"music": "{Album Artist}/{Album} ({Year})/{Track:00} - {Title}"}
    library_settings.save_settings(db_session, lib.id, {"naming_template": tpl})
    db_session.commit()

    saved = json.loads(db_session.get(Library, lib.id).settings or "{}")
    assert saved["naming_template"]["music"] == tpl["music"]


def test_save_settings_round_trips_tag_profile(db_session):
    lib = _make_library(db_session, "music")
    profile = {"id3_version": "2.4", "embed_art": True}
    library_settings.save_settings(db_session, lib.id, {"tag_profile": profile})
    db_session.commit()

    saved = json.loads(db_session.get(Library, lib.id).settings or "{}")
    assert saved["tag_profile"]["id3_version"] == "2.4"
    assert saved["tag_profile"]["embed_art"] is True


def test_save_settings_does_not_commit(db_session):
    lib = _make_library(db_session, "movies")
    db_session.commit()

    library_settings.save_settings(db_session, lib.id, {"ownership": "arr"})
    # Before commit the Python object has the value but the old DB row is not yet written.
    # No error means flush succeeded.
    db_session.rollback()

    # After rollback, the change should be gone
    db_session.expire_all()
    lib2 = db_session.get(Library, lib.id)
    assert lib2.settings is None


# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------

def test_get_settings_returns_empty_dict_for_null_settings(db_session):
    lib = _make_library(db_session, "tv")
    result = library_settings.get_settings(db_session, lib.id)
    assert result == {}


def test_get_settings_returns_parsed_json(db_session):
    lib = _make_library(db_session, "tv", json.dumps({"ownership": "arr", "recycle_folder": ".trash"}))
    result = library_settings.get_settings(db_session, lib.id)
    assert result["ownership"] == "arr"
    assert result["recycle_folder"] == ".trash"


# ---------------------------------------------------------------------------
# set_ownership helper
# ---------------------------------------------------------------------------

def test_set_ownership_persists(db_session):
    lib = _make_library(db_session, "music")
    library_settings.set_ownership(db_session, lib.id, "arr")
    db_session.commit()

    assert library_settings.get_ownership(db_session, lib.id) == "arr"
