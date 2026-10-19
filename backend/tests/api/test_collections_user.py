"""User-facing collections API tests."""
from __future__ import annotations

import uuid

from app.models.collection import Collection, CollectionItem
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie


def _movie(db) -> Movie:
    m = Movie(title="Test Movie")
    db.add(m)
    db.flush()
    return m


def _mf(db, movie: Movie) -> MediaFile:
    mf = MediaFile(kind=MediaKind.movie, ref_id=movie.id,
                   path=f"/movies/{uuid.uuid4().hex}.mkv", scan_state=ScanState.ready)
    db.add(mf)
    db.flush()
    return mf


def _collection(db, name="Col", *, is_auto=False) -> Collection:
    c = Collection(id=uuid.uuid4(), name=name, kind="movies", is_auto=is_auto)
    db.add(c)
    db.flush()
    return c


def _item(db, collection: Collection, movie: Movie) -> CollectionItem:
    i = CollectionItem(id=uuid.uuid4(), collection_id=collection.id,
                       entity_kind="movie", entity_id=movie.id)
    db.add(i)
    db.flush()
    return i


# ---------------------------------------------------------------------------
# GET /api/library/collections/
# ---------------------------------------------------------------------------

def test_list_collections_empty(client, db_session):
    r = client.get("/api/library/collections/")
    assert r.status_code == 200
    assert r.json() == []


def test_list_collections_shows_collection_with_visible_movie(client, db_session):
    m = _movie(db_session)
    _mf(db_session, m)
    c = _collection(db_session, "Sci-Fi")
    _item(db_session, c, m)
    db_session.commit()

    r = client.get("/api/library/collections/")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "Sci-Fi"
    assert body[0]["item_count"] == 1


def test_list_collections_hides_empty_collection(client, db_session):
    c = _collection(db_session, "Empty")
    db_session.commit()

    r = client.get("/api/library/collections/")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /api/library/collections/{id}
# ---------------------------------------------------------------------------

def test_get_collection_detail(client, db_session):
    m = _movie(db_session)
    _mf(db_session, m)
    c = _collection(db_session, "Detail")
    _item(db_session, c, m)
    db_session.commit()

    r = client.get(f"/api/library/collections/{c.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Detail"
    assert len(body["items"]) == 1
    assert body["items"][0]["entity_kind"] == "movie"


def test_get_collection_detail_404_missing(client, db_session):
    r = client.get(f"/api/library/collections/{uuid.uuid4()}")
    assert r.status_code == 404


def test_get_collection_detail_404_no_visible_items(client, db_session):
    # Collection exists but movie has no ready media file.
    m = _movie(db_session)
    c = _collection(db_session, "No Files")
    _item(db_session, c, m)
    db_session.commit()

    r = client.get(f"/api/library/collections/{c.id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Hidden-library filtering (member user)
# ---------------------------------------------------------------------------

def test_list_collections_hidden_library_omits_collection(db_session):
    """A member user with a library hidden does not see collections whose only
    items are in that library (exercises the library-access filter path)."""
    from fastapi.testclient import TestClient

    from app.api.deps import current_user, get_db
    from app.main import app
    from app.models.library import Library, LibraryKind, UserLibraryAccess
    from app.models.user import User

    lib = Library(id=uuid.uuid4(), name="Hidden Lib", kind=LibraryKind.movies)
    db_session.add(lib)
    db_session.flush()

    member = User(id=uuid.uuid4(), username="member-hidden", display_name="M",
                  password_hash="x", role="member", is_active=True)
    db_session.add(member)
    db_session.flush()

    # Hide the library from this member.
    db_session.add(UserLibraryAccess(id=uuid.uuid4(),
                                     user_id=member.id, library_id=lib.id))

    m = _movie(db_session)
    hidden_mf = MediaFile(kind=MediaKind.movie, ref_id=m.id,
                          path=f"/movies/{uuid.uuid4().hex}.mkv",
                          scan_state=ScanState.ready, library_id=lib.id)
    db_session.add(hidden_mf)

    c = _collection(db_session, "Only Hidden")
    _item(db_session, c, m)
    db_session.commit()

    def _db():
        try:
            yield db_session
        finally:
            pass

    def _user():
        return member

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_user] = _user
    try:
        tc = TestClient(app)
        # Collection must not appear for this user.
        r = tc.get("/api/library/collections/")
        assert r.status_code == 200
        assert r.json() == []

        # Detail endpoint also returns 404.
        r = tc.get(f"/api/library/collections/{c.id}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
