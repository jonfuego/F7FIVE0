"""Unit tests for services/bulk_actions.py."""
from __future__ import annotations

import uuid

import pytest

from app.models.app_setting import AppSetting
from app.models.movie import Movie
from app.services import bulk_actions as ba


# ---------------------------------------------------------------------------
# is_running
# ---------------------------------------------------------------------------

def test_is_running_false_when_no_status(db_session):
    assert ba.is_running(db_session) is False


def test_is_running_true_when_running(db_session):
    row = AppSetting(key=ba.BULK_JOB_KEY, value={"state": "running"})
    db_session.add(row)
    db_session.commit()
    assert ba.is_running(db_session) is True


def test_is_running_false_when_idle(db_session):
    row = AppSetting(key=ba.BULK_JOB_KEY, value={"state": "idle"})
    db_session.add(row)
    db_session.commit()
    assert ba.is_running(db_session) is False


# ---------------------------------------------------------------------------
# run_bulk_action: lock / unlock
# The function opens its own db sessions (app.db.db_session) which share the
# StaticPool connection with the test fixture session.
# ---------------------------------------------------------------------------

def test_run_bulk_lock_sets_status_done(db_session):
    m = Movie(title="Lock Test")
    db_session.add(m)
    db_session.commit()

    ba.run_bulk_action("lock", "movie", [m.id])

    db_session.expire_all()
    row = db_session.get(AppSetting, ba.BULK_JOB_KEY)
    assert row is not None
    assert row.value["state"] == "done"
    assert row.value["done"] == 1
    assert row.value["errors"] == 0


def test_run_bulk_unlock_sets_status_done(db_session):
    m = Movie(title="Unlock Test")
    db_session.add(m)
    db_session.commit()

    ba.run_bulk_action("unlock", "movie", [m.id])

    db_session.expire_all()
    row = db_session.get(AppSetting, ba.BULK_JOB_KEY)
    assert row is not None
    assert row.value["state"] == "done"


# ---------------------------------------------------------------------------
# run_bulk_action: add_to_collection
# ---------------------------------------------------------------------------

def test_run_bulk_add_to_collection(db_session):
    from app.models.collection import Collection, CollectionItem
    from sqlalchemy import select

    m = Movie(title="Bulk Add Movie")
    db_session.add(m)
    coll = Collection(id=uuid.uuid4(), name="Bulk", kind="movies", is_auto=False)
    db_session.add(coll)
    db_session.commit()

    ba.run_bulk_action("add_to_collection", "movie", [m.id],
                       params={"collection_id": str(coll.id)})

    db_session.expire_all()
    item = db_session.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == coll.id,
            CollectionItem.entity_id == m.id,
        )
    )
    assert item is not None


# ---------------------------------------------------------------------------
# run_bulk_action: unknown action error counted
# ---------------------------------------------------------------------------

def test_run_bulk_unknown_action_counted_as_error(db_session):
    ba.run_bulk_action("not_a_real_action", "movie", [uuid.uuid4()])

    db_session.expire_all()
    row = db_session.get(AppSetting, ba.BULK_JOB_KEY)
    assert row is not None
    assert row.value["state"] == "done"
    assert row.value["errors"] == 1
    assert row.value["done"] == 0


# ---------------------------------------------------------------------------
# Lock prevents concurrent runs
# ---------------------------------------------------------------------------

def test_second_run_returns_when_locked(db_session):
    acquired = ba._lock.acquire(blocking=False)
    assert acquired, "lock should have been free"
    try:
        # Should return immediately; no status written.
        ba.run_bulk_action("lock", "movie", [uuid.uuid4()])
        db_session.expire_all()
        row = db_session.get(AppSetting, ba.BULK_JOB_KEY)
        assert row is None
    finally:
        ba._lock.release()
