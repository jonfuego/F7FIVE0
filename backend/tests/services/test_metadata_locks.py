"""Unit tests for app/services/metadata_locks.py."""
from __future__ import annotations

import uuid

from app.services import metadata_locks


def _eid() -> uuid.UUID:
    return uuid.uuid4()


def test_is_locked_false_initially(db_session):
    assert not metadata_locks.is_locked(db_session, "movie", _eid(), "title")


def test_set_and_is_locked(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "movie", eid, ["title", "year"])
    assert metadata_locks.is_locked(db_session, "movie", eid, "title")
    assert metadata_locks.is_locked(db_session, "movie", eid, "year")
    assert not metadata_locks.is_locked(db_session, "movie", eid, "overview")


def test_set_locks_idempotent(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "movie", eid, ["title"])
    metadata_locks.set_locks(db_session, "movie", eid, ["title"])  # no error
    assert metadata_locks.is_locked(db_session, "movie", eid, "title")


def test_clear_locks_removes_specific_fields(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "movie", eid, ["title", "year", "overview"])
    metadata_locks.clear_locks(db_session, "movie", eid, ["title", "year"])
    assert not metadata_locks.is_locked(db_session, "movie", eid, "title")
    assert not metadata_locks.is_locked(db_session, "movie", eid, "year")
    assert metadata_locks.is_locked(db_session, "movie", eid, "overview")


def test_clear_locks_empty_list_is_noop(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "movie", eid, ["title"])
    metadata_locks.clear_locks(db_session, "movie", eid, [])
    assert metadata_locks.is_locked(db_session, "movie", eid, "title")


def test_locked_fields_returns_set(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "artist", eid, ["name", "country"])
    assert metadata_locks.locked_fields(db_session, "artist", eid) == {"name", "country"}


def test_locked_fields_empty_for_unknown_entity(db_session):
    assert metadata_locks.locked_fields(db_session, "movie", _eid()) == set()


def test_locks_are_entity_kind_scoped(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "movie", eid, ["title"])
    # Same entity_id but different kind must not share locks.
    assert not metadata_locks.is_locked(db_session, "series", eid, "title")
    assert metadata_locks.locked_fields(db_session, "series", eid) == set()


def test_bulk_locked_fields_returns_per_id_sets(db_session):
    eid1 = _eid()
    eid2 = _eid()
    eid3 = _eid()
    metadata_locks.set_locks(db_session, "movie", eid1, ["title"])
    metadata_locks.set_locks(db_session, "movie", eid2, ["year", "overview"])
    result = metadata_locks.bulk_locked_fields(db_session, "movie", [eid1, eid2, eid3])
    assert result[eid1] == {"title"}
    assert result[eid2] == {"year", "overview"}
    assert result[eid3] == set()


def test_bulk_locked_fields_empty_input(db_session):
    assert metadata_locks.bulk_locked_fields(db_session, "movie", []) == {}


def test_bulk_locked_fields_unknown_kind(db_session):
    eid = _eid()
    metadata_locks.set_locks(db_session, "movie", eid, ["title"])
    result = metadata_locks.bulk_locked_fields(db_session, "series", [eid])
    assert result[eid] == set()
