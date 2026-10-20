"""Collections service: sync TMDB auto-collections and serve user-filtered views."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.collection import Collection, CollectionItem
from app.models.media_file import MediaFile, ScanState
from app.models.movie import Movie
from app.models.user import User
from app.services import library_access


def sync_tmdb_collections(db: Session) -> int:
    """Upsert one Collection per distinct tmdb_collection_id in movies, and one
    CollectionItem per movie with that id. Returns the number of rows upserted."""
    rows = db.execute(
        select(Movie.id, Movie.tmdb_collection_id, Movie.tmdb_collection_name).where(
            Movie.tmdb_collection_id.is_not(None)
        )
    ).all()

    # Group by tmdb_collection_id
    by_coll: dict[int, list] = {}
    names: dict[int, str] = {}
    for movie_id, coll_id, coll_name in rows:
        by_coll.setdefault(coll_id, []).append(movie_id)
        if coll_name:
            names[coll_id] = coll_name

    count = 0
    for coll_id, movie_ids in by_coll.items():
        name = names.get(coll_id) or f"Collection {coll_id}"
        coll = db.scalar(
            select(Collection).where(Collection.tmdb_collection_id == coll_id)
        )
        if coll is None:
            coll = Collection(
                id=uuid.uuid4(),
                name=name,
                kind="movies",
                tmdb_collection_id=coll_id,
                is_auto=True,
            )
            db.add(coll)
            db.flush()
            count += 1
        else:
            coll.name = name
            coll.updated_at = datetime.now(timezone.utc)
            count += 1

        for movie_id in movie_ids:
            existing = db.scalar(
                select(CollectionItem).where(
                    CollectionItem.collection_id == coll.id,
                    CollectionItem.entity_kind == "movie",
                    CollectionItem.entity_id == movie_id,
                )
            )
            if existing is None:
                db.add(CollectionItem(
                    id=uuid.uuid4(),
                    collection_id=coll.id,
                    entity_kind="movie",
                    entity_id=movie_id,
                ))
                count += 1

    db.commit()
    return count


def get_for_user(db: Session, user: User) -> list[dict]:
    """Collections visible to the user (at least one item in a visible library)."""
    hidden = library_access.hidden_library_ids(db, user)

    collections = db.scalars(select(Collection)).all()
    out = []
    for coll in collections:
        items = db.scalars(
            select(CollectionItem).where(CollectionItem.collection_id == coll.id)
        ).all()
        visible_items = _filter_visible_items(db, items, hidden)
        if not visible_items:
            continue
        out.append({
            "id": coll.id,
            "name": coll.name,
            "kind": coll.kind,
            "item_count": len(visible_items),
            "tmdb_collection_id": coll.tmdb_collection_id,
            "is_auto": coll.is_auto,
            "description": coll.description,
        })
    return out


def get_collection_detail(
    db: Session, user: User, collection_id: uuid.UUID,
) -> Optional[dict]:
    """Collection with items visible to the user, or None if none are visible."""
    coll = db.get(Collection, collection_id)
    if coll is None:
        return None
    hidden = library_access.hidden_library_ids(db, user)
    items = db.scalars(
        select(CollectionItem).where(CollectionItem.collection_id == coll.id)
    ).all()
    visible_items = _filter_visible_items(db, items, hidden)
    if not visible_items:
        return None
    return {
        "id": coll.id,
        "name": coll.name,
        "kind": coll.kind,
        "item_count": len(visible_items),
        "tmdb_collection_id": coll.tmdb_collection_id,
        "is_auto": coll.is_auto,
        "description": coll.description,
        "items": [
            {"entity_kind": i.entity_kind, "entity_id": i.entity_id, "sort_order": i.sort_order}
            for i in visible_items
        ],
    }


def add_items(
    db: Session,
    collection_id: uuid.UUID,
    entity_kind: str,
    entity_ids: list[uuid.UUID],
) -> int:
    """Bulk-add items to a collection. Returns count of rows added."""
    added = 0
    for entity_id in entity_ids:
        existing = db.scalar(
            select(CollectionItem).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.entity_kind == entity_kind,
                CollectionItem.entity_id == entity_id,
            )
        )
        if existing is None:
            db.add(CollectionItem(
                id=uuid.uuid4(),
                collection_id=collection_id,
                entity_kind=entity_kind,
                entity_id=entity_id,
            ))
            added += 1
    db.flush()
    return added


def remove_items(
    db: Session,
    collection_id: uuid.UUID,
    entity_kind: str,
    entity_ids: list[uuid.UUID],
) -> int:
    """Bulk-remove items from a collection. Returns count of rows removed."""
    result = db.execute(
        delete(CollectionItem).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.entity_kind == entity_kind,
            CollectionItem.entity_id.in_(entity_ids),
        )
    )
    db.flush()
    return result.rowcount


def _filter_visible_items(
    db: Session,
    items: list[CollectionItem],
    hidden: set[uuid.UUID],
) -> list[CollectionItem]:
    """Keep only items that have at least one ready media file in a visible library."""
    out = []
    for item in items:
        files = db.scalars(
            select(MediaFile).where(
                MediaFile.kind == item.entity_kind,
                MediaFile.ref_id == item.entity_id,
                MediaFile.scan_state == ScanState.ready,
            )
        ).all()
        visible = [f for f in files if f.library_id is None or f.library_id not in hidden]
        if visible:
            out.append(item)
    return out
