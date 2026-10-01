"""Cross-device audio queue.

One row per user, mirroring the shape the client kept in localStorage.
The library BFF in the Next app forwards `/api/library/queue` to this
router (the BFF strips the `library/` namespace), so the URL space stays
consistent with the rest of the library reads.

Endpoints:
  GET    /  hydrate the current queue (empty default if no row)
  PUT    /  upsert the queue for the current user
  DELETE /  clear the row entirely
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models.playback import PlaybackQueue
from app.models.user import User


router = APIRouter(prefix="/queue", tags=["library"])


class _QueueItem(BaseModel):
    # Items can carry extra UI fields (artist_name, cover_path, track_id,
    # ...). We require only the two the player can't do without.
    model_config = ConfigDict(extra="allow")

    media_file_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)


class QueueUpsertRequest(BaseModel):
    items: list[_QueueItem]
    current_index: Optional[int] = None
    repeat_mode: str = Field(default="off")
    shuffle: bool = False
    last_writer_id: Optional[str] = Field(default=None, max_length=64)


class QueueOut(BaseModel):
    items: list[Any]
    current_index: Optional[int]
    repeat_mode: str
    shuffle: bool
    last_writer_id: Optional[str]
    updated_at: datetime


_EMPTY: dict[str, Any] = {
    "items": [],
    "current_index": None,
    "repeat_mode": "off",
    "shuffle": False,
    "last_writer_id": None,
}


@router.get("/", response_model=QueueOut)
def get_queue(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QueueOut:
    row = db.get(PlaybackQueue, user.id)
    if row is None:
        return QueueOut(updated_at=datetime.now(timezone.utc), **_EMPTY)
    return QueueOut(
        items=row.items or [],
        current_index=row.current_index,
        repeat_mode=row.repeat_mode,
        shuffle=bool(row.shuffle),
        last_writer_id=row.last_writer_id,
        updated_at=row.updated_at,
    )


@router.put("/", response_model=QueueOut)
def put_queue(
    body: Annotated[QueueUpsertRequest, Body(...)],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QueueOut:
    if body.repeat_mode not in {"off", "all", "one"}:
        raise HTTPException(status_code=422, detail="invalid_repeat_mode")
    n = len(body.items)
    if body.current_index is not None and not (0 <= body.current_index < n):
        # Allow null when the queue is empty or stopped; reject any other
        # out-of-range index so a corrupt client can't desync the row.
        raise HTTPException(status_code=422, detail="current_index_out_of_range")

    items_payload = [item.model_dump(mode="json") for item in body.items]
    now = datetime.now(timezone.utc)

    row = db.get(PlaybackQueue, user.id)
    if row is None:
        row = PlaybackQueue(
            user_id=user.id,
            items=items_payload,
            current_index=body.current_index,
            repeat_mode=body.repeat_mode,
            shuffle=body.shuffle,
            last_writer_id=body.last_writer_id,
            updated_at=now,
        )
        db.add(row)
    else:
        row.items = items_payload
        row.current_index = body.current_index
        row.repeat_mode = body.repeat_mode
        row.shuffle = body.shuffle
        row.last_writer_id = body.last_writer_id
        row.updated_at = now

    db.commit()
    db.refresh(row)
    return QueueOut(
        items=row.items or [],
        current_index=row.current_index,
        repeat_mode=row.repeat_mode,
        shuffle=bool(row.shuffle),
        last_writer_id=row.last_writer_id,
        updated_at=row.updated_at,
    )


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
def delete_queue(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    row = db.get(PlaybackQueue, user.id)
    if row is not None:
        db.delete(row)
        db.commit()
