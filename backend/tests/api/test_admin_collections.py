"""Admin collections API tests."""
from __future__ import annotations

import uuid

import pytest

from app.models.collection import Collection, CollectionItem
from app.models.movie import Movie


def _make_collection(db, *, name="Test Collection", is_auto=False) -> Collection:
    c = Collection(id=uuid.uuid4(), name=name, kind="movies", is_auto=is_auto)
    db.add(c)
    db.commit()
    return c


# ---------------------------------------------------------------------------
# GET /api/admin/collections/
# ---------------------------------------------------------------------------

def test_list_collections_empty(client, db_session):
    r = client.get("/api/admin/collections/")
    assert r.status_code == 200
    assert r.json() == []


def test_list_collections_returns_rows(client, db_session):
    _make_collection(db_session, name="Alpha")
    _make_collection(db_session, name="Beta")
    r = client.get("/api/admin/collections/")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert "Alpha" in names and "Beta" in names


# ---------------------------------------------------------------------------
# POST /api/admin/collections/
# ---------------------------------------------------------------------------

def test_create_collection(client, db_session):
    r = client.post("/api/admin/collections/", json={"name": "Sci-Fi Classics", "kind": "movies"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Sci-Fi Classics"
    assert body["is_auto"] is False
    assert body["id"] is not None


def test_create_collection_default_kind(client, db_session):
    r = client.post("/api/admin/collections/", json={"name": "Mixed"})
    assert r.status_code == 201
    assert r.json()["kind"] == "movies"


# ---------------------------------------------------------------------------
# PATCH /api/admin/collections/{id}
# ---------------------------------------------------------------------------

def test_update_collection_name(client, db_session):
    c = _make_collection(db_session, name="Original")
    r = client.patch(f"/api/admin/collections/{c.id}", json={"name": "Updated"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated"


def test_update_collection_not_found(client, db_session):
    r = client.patch(f"/api/admin/collections/{uuid.uuid4()}", json={"name": "X"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/admin/collections/{id}
# ---------------------------------------------------------------------------

def test_delete_manual_collection(client, db_session):
    c = _make_collection(db_session, name="Deletable", is_auto=False)
    r = client.delete(f"/api/admin/collections/{c.id}")
    assert r.status_code == 204
    assert db_session.get(Collection, c.id) is None


def test_delete_auto_collection_returns_409(client, db_session):
    c = _make_collection(db_session, name="TMDB Auto", is_auto=True)
    r = client.delete(f"/api/admin/collections/{c.id}")
    assert r.status_code == 409
    assert r.json()["detail"] == "auto_collection"
    assert db_session.get(Collection, c.id) is not None


def test_delete_not_found(client, db_session):
    r = client.delete(f"/api/admin/collections/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/admin/collections/{id}/items
# ---------------------------------------------------------------------------

def test_add_items_to_collection(client, db_session):
    c = _make_collection(db_session, name="With Items")
    movie_id = uuid.uuid4()
    r = client.post(
        f"/api/admin/collections/{c.id}/items",
        json={"entity_kind": "movie", "entity_ids": [str(movie_id)]},
    )
    assert r.status_code == 204

    from sqlalchemy import select
    item = db_session.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == c.id,
            CollectionItem.entity_id == movie_id,
        )
    )
    assert item is not None


def test_add_items_404_unknown_collection(client, db_session):
    r = client.post(
        f"/api/admin/collections/{uuid.uuid4()}/items",
        json={"entity_kind": "movie", "entity_ids": [str(uuid.uuid4())]},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/admin/collections/{id}/items
# ---------------------------------------------------------------------------

def test_remove_items_from_collection(client, db_session):
    import json as _json
    c = _make_collection(db_session, name="Remove Test")
    movie_id = uuid.uuid4()
    db_session.add(CollectionItem(id=uuid.uuid4(), collection_id=c.id,
                                  entity_kind="movie", entity_id=movie_id))
    db_session.commit()

    r = client.request(
        "DELETE",
        f"/api/admin/collections/{c.id}/items",
        content=_json.dumps({"entity_kind": "movie", "entity_ids": [str(movie_id)]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 204

    from sqlalchemy import select
    item = db_session.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == c.id,
            CollectionItem.entity_id == movie_id,
        )
    )
    assert item is None


def test_remove_items_404_unknown_collection(client, db_session):
    import json as _json
    r = client.request(
        "DELETE",
        f"/api/admin/collections/{uuid.uuid4()}/items",
        content=_json.dumps({"entity_kind": "movie", "entity_ids": [str(uuid.uuid4())]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 404
