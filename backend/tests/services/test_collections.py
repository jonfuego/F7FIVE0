"""Unit tests for services/collections.py."""
from __future__ import annotations

import uuid

import pytest

from app.models.collection import Collection, CollectionItem
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.user import User
from app.services import collections as svc


def _make_user(db) -> User:
    u = User(username=f"u-{uuid.uuid4().hex[:6]}", display_name="U",
             password_hash="x", role="member", is_active=True)
    db.add(u)
    db.flush()
    return u


def _make_movie(db, *, tmdb_coll_id=None, coll_name=None) -> Movie:
    m = Movie(title="Movie", tmdb_collection_id=tmdb_coll_id,
              tmdb_collection_name=coll_name)
    db.add(m)
    db.flush()
    return m


def _make_mf(db, movie: Movie, *, state=ScanState.ready) -> MediaFile:
    mf = MediaFile(kind=MediaKind.movie, ref_id=movie.id,
                   path=f"/movies/{uuid.uuid4().hex}.mkv", scan_state=state)
    db.add(mf)
    db.flush()
    return mf


def _make_collection(db, *, name="Test", is_auto=False) -> Collection:
    c = Collection(id=uuid.uuid4(), name=name, kind="movies", is_auto=is_auto)
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------------------
# sync_tmdb_collections
# ---------------------------------------------------------------------------

def test_sync_creates_collection_and_item(db_session):
    m = _make_movie(db_session, tmdb_coll_id=100, coll_name="The Avengers Collection")
    _make_mf(db_session, m)
    db_session.commit()

    count = svc.sync_tmdb_collections(db_session)
    assert count >= 2  # 1 collection + 1 item

    from sqlalchemy import select
    coll = db_session.scalar(
        select(Collection).where(Collection.tmdb_collection_id == 100)
    )
    assert coll is not None
    assert coll.name == "The Avengers Collection"
    assert coll.is_auto is True

    item = db_session.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == coll.id,
            CollectionItem.entity_id == m.id,
        )
    )
    assert item is not None


def test_sync_updates_existing_collection_name(db_session):
    m = _make_movie(db_session, tmdb_coll_id=200, coll_name="Old Name")
    _make_mf(db_session, m)
    svc.sync_tmdb_collections(db_session)

    m.tmdb_collection_name = "New Name"
    db_session.commit()

    svc.sync_tmdb_collections(db_session)

    from sqlalchemy import select
    coll = db_session.scalar(
        select(Collection).where(Collection.tmdb_collection_id == 200)
    )
    assert coll.name == "New Name"


def test_sync_groups_movies_in_same_collection(db_session):
    m1 = _make_movie(db_session, tmdb_coll_id=300, coll_name="Series")
    m2 = _make_movie(db_session, tmdb_coll_id=300, coll_name="Series")
    _make_mf(db_session, m1)
    _make_mf(db_session, m2)
    db_session.commit()

    svc.sync_tmdb_collections(db_session)

    from sqlalchemy import select, func
    count = db_session.scalar(
        select(func.count()).select_from(Collection).where(Collection.tmdb_collection_id == 300)
    )
    assert count == 1

    item_count = db_session.scalar(
        select(func.count()).select_from(CollectionItem).where(
            CollectionItem.entity_kind == "movie"
        )
    )
    assert item_count == 2


def test_sync_idempotent(db_session):
    m = _make_movie(db_session, tmdb_coll_id=400, coll_name="Idempotent")
    _make_mf(db_session, m)
    db_session.commit()

    svc.sync_tmdb_collections(db_session)
    svc.sync_tmdb_collections(db_session)

    from sqlalchemy import select, func
    coll_count = db_session.scalar(
        select(func.count()).select_from(Collection).where(Collection.tmdb_collection_id == 400)
    )
    assert coll_count == 1


# ---------------------------------------------------------------------------
# get_for_user
# ---------------------------------------------------------------------------

def test_get_for_user_returns_collection_with_visible_item(db_session):
    u = _make_user(db_session)
    m = _make_movie(db_session)
    _make_mf(db_session, m)
    c = _make_collection(db_session, name="My Picks")
    db_session.add(CollectionItem(id=uuid.uuid4(), collection_id=c.id,
                                  entity_kind="movie", entity_id=m.id))
    db_session.commit()

    results = svc.get_for_user(db_session, u)
    assert any(r["id"] == c.id for r in results)


def test_get_for_user_excludes_empty_collection(db_session):
    u = _make_user(db_session)
    c = _make_collection(db_session, name="Empty")
    db_session.commit()

    results = svc.get_for_user(db_session, u)
    assert not any(r["id"] == c.id for r in results)


def test_get_for_user_hidden_library_excludes_collection(db_session):
    """get_for_user does not return a collection whose only item is in a library
    the user has hidden (the library-access filter path)."""
    from app.models.library import Library, LibraryKind, UserLibraryAccess

    lib = Library(id=uuid.uuid4(), name="Private Lib", kind=LibraryKind.movies)
    db_session.add(lib)
    db_session.flush()

    u = _make_user(db_session)
    # A UserLibraryAccess row hides the library from this user.
    db_session.add(UserLibraryAccess(id=uuid.uuid4(), user_id=u.id, library_id=lib.id))

    m = _make_movie(db_session)
    # The only ready file for this movie is in the hidden library.
    hidden_mf = MediaFile(
        kind=MediaKind.movie, ref_id=m.id,
        path=f"/movies/{uuid.uuid4().hex}.mkv",
        scan_state=ScanState.ready,
        library_id=lib.id,
    )
    db_session.add(hidden_mf)

    c = _make_collection(db_session, name="Hidden Only")
    db_session.add(CollectionItem(id=uuid.uuid4(), collection_id=c.id,
                                  entity_kind="movie", entity_id=m.id))
    db_session.commit()

    # User cannot see the library, so the collection must be absent.
    results = svc.get_for_user(db_session, u)
    assert not any(r["id"] == c.id for r in results)


# ---------------------------------------------------------------------------
# add_items / remove_items
# ---------------------------------------------------------------------------

def test_add_and_remove_items(db_session):
    c = _make_collection(db_session)
    m = _make_movie(db_session)
    db_session.commit()

    added = svc.add_items(db_session, c.id, "movie", [m.id])
    db_session.commit()
    assert added == 1

    # Idempotent: adding again returns 0
    added2 = svc.add_items(db_session, c.id, "movie", [m.id])
    db_session.commit()
    assert added2 == 0

    removed = svc.remove_items(db_session, c.id, "movie", [m.id])
    db_session.commit()
    assert removed == 1


# ---------------------------------------------------------------------------
# get_collection_detail
# ---------------------------------------------------------------------------

def test_get_collection_detail_returns_none_for_missing_id(db_session):
    u = _make_user(db_session)
    result = svc.get_collection_detail(db_session, u, uuid.uuid4())
    assert result is None


def test_get_collection_detail_returns_items(db_session):
    u = _make_user(db_session)
    m = _make_movie(db_session)
    _make_mf(db_session, m)
    c = _make_collection(db_session, name="Detail Test")
    db_session.add(CollectionItem(id=uuid.uuid4(), collection_id=c.id,
                                  entity_kind="movie", entity_id=m.id))
    db_session.commit()

    detail = svc.get_collection_detail(db_session, u, c.id)
    assert detail is not None
    assert detail["name"] == "Detail Test"
    assert len(detail["items"]) == 1
    assert detail["items"][0]["entity_id"] == m.id
