"""User-facing collections endpoints.

Endpoints:
  GET /api/library/collections       - list user-visible collections
  GET /api/library/collections/{id}  - collection detail with visible items

Require a signed-in user.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models.user import User
from app.services import collections as collections_service

router = APIRouter(prefix="/library/collections", tags=["collections"])


class CollectionSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: Optional[str] = None
    item_count: int
    tmdb_collection_id: Optional[int] = None
    is_auto: bool
    description: Optional[str] = None


class CollectionDetailOut(CollectionSummaryOut):
    items: list[dict]


@router.get("/", response_model=list[CollectionSummaryOut])
def list_collections(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CollectionSummaryOut]:
    rows = collections_service.get_for_user(db, user)
    return [CollectionSummaryOut(**r) for r in rows]


@router.get("/{collection_id}", response_model=CollectionDetailOut)
def get_collection(
    collection_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CollectionDetailOut:
    detail = collections_service.get_collection_detail(db, user, collection_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    return CollectionDetailOut(**detail)
