"""Admin collections endpoints.

Endpoints:
  GET    /api/admin/collections           - list all collections
  POST   /api/admin/collections           - create a manual collection
  PATCH  /api/admin/collections/{id}      - update name/description
  DELETE /api/admin/collections/{id}      - delete a manual collection (409 if auto)
  POST   /api/admin/collections/{id}/items   - bulk-add items
  DELETE /api/admin/collections/{id}/items   - bulk-remove items

All admin-only.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.collection import Collection
from app.models.user import User
from app.services import collections as collections_service

router = APIRouter(prefix="/collections", tags=["admin-collections"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: Optional[str] = None
    tmdb_collection_id: Optional[int] = None
    is_auto: bool
    description: Optional[str] = None


class CollectionCreateRequest(BaseModel):
    name: str
    kind: Optional[str] = None
    description: Optional[str] = None


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CollectionItemsRequest(BaseModel):
    entity_kind: str
    entity_ids: list[uuid.UUID]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[CollectionOut])
def list_collections(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CollectionOut]:
    rows = db.scalars(select(Collection)).all()
    return [
        CollectionOut(
            id=c.id,
            name=c.name,
            kind=c.kind,
            tmdb_collection_id=c.tmdb_collection_id,
            is_auto=c.is_auto,
            description=c.description,
        )
        for c in rows
    ]


@router.post("/", response_model=CollectionOut, status_code=201)
def create_collection(
    body: CollectionCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> CollectionOut:
    coll = Collection(
        id=uuid.uuid4(),
        name=body.name,
        kind=body.kind or "movies",
        is_auto=False,
        created_by=admin.id,
        description=body.description,
    )
    db.add(coll)
    db.commit()
    db.refresh(coll)
    return CollectionOut(
        id=coll.id,
        name=coll.name,
        kind=coll.kind,
        tmdb_collection_id=coll.tmdb_collection_id,
        is_auto=coll.is_auto,
        description=coll.description,
    )


@router.patch("/{collection_id}", response_model=CollectionOut)
def update_collection(
    collection_id: uuid.UUID,
    body: CollectionUpdateRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> CollectionOut:
    coll = db.get(Collection, collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    if body.name is not None:
        coll.name = body.name
    if body.description is not None:
        coll.description = body.description
    db.commit()
    db.refresh(coll)
    return CollectionOut(
        id=coll.id,
        name=coll.name,
        kind=coll.kind,
        tmdb_collection_id=coll.tmdb_collection_id,
        is_auto=coll.is_auto,
        description=coll.description,
    )


@router.delete("/{collection_id}", status_code=204)
def delete_collection(
    collection_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    coll = db.get(Collection, collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    if coll.is_auto:
        raise HTTPException(status_code=409, detail="auto_collection")
    db.delete(coll)
    db.commit()


@router.post("/{collection_id}/items", status_code=204)
def add_collection_items(
    collection_id: uuid.UUID,
    body: CollectionItemsRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    coll = db.get(Collection, collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    collections_service.add_items(db, collection_id, body.entity_kind, body.entity_ids)
    db.commit()


@router.delete("/{collection_id}/items", status_code=204)
def remove_collection_items(
    collection_id: uuid.UUID,
    body: CollectionItemsRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    coll = db.get(Collection, collection_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    collections_service.remove_items(db, collection_id, body.entity_kind, body.entity_ids)
    db.commit()
