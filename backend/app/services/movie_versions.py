"""Movie version management: merge twin movies in the same library.

A "twin" is a second Movie row for the same film: an older folder scan made
one for a copy in a different folder (it matched by tmdb_id or by the same
normalized title and year). Twins in the SAME library become additional
media_files rows ("versions") on the primary movie; twins in DIFFERENT
libraries stay separate entries per Jon's decision (2026-10-18).

The folder scan attaches a same-library copy directly
(`scan_library._match_movie`); `merge_twins` runs after every folder scan
(`scheduler._scan_folders`) and folds the twins older scans left behind.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.media_file import MediaFile, MediaKind
from app.models.movie import Movie

log = logging.getLogger("f7five0.movie_versions")


def _normalize_title(title: str) -> str:
    """Lowercase, strip leading 'the '/'a '/'an ', collapse whitespace."""
    t = title.strip().lower()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _is_twin(a: Movie, b: Movie) -> bool:
    """True when two movies should be treated as versions of the same film.

    Same tmdb_id (when both have one), or same normalized title and year
    (the rule scan_library._tmdb_twin uses).
    """
    if a.tmdb_id and b.tmdb_id:
        return a.tmdb_id == b.tmdb_id
    if a.year and b.year and a.year == b.year:
        return _normalize_title(a.title) == _normalize_title(b.title)
    return False


def _rank(m: Movie) -> tuple:
    """Sort key for the entry that survives a merge: an *arr-owned row first
    (a sync would recreate it), then one with a TMDB id, then the oldest."""
    created = m.created_at.replace(tzinfo=None) if m.created_at else datetime.max
    return (m.radarr_id is None, m.tmdb_id is None, created, str(m.id))


def merge_twins(db: Session) -> int:
    """For each group of twins in the same library, fold the secondaries into
    the primary. Media file ids never change, so watch history and progress
    (keyed by file) stay. Movies in different libraries are never merged.
    Commits when something merged. Returns the number of movie rows deleted.

    A movie's library is the `library_id` of its oldest file; a movie with no
    files is left alone.
    """
    libs: dict[uuid.UUID, Optional[uuid.UUID]] = {}
    for ref_id, lib_id in db.execute(
        select(MediaFile.ref_id, MediaFile.library_id)
        .where(MediaFile.kind == MediaKind.movie)
        .order_by(MediaFile.created_at, MediaFile.id)
    ).all():
        libs.setdefault(ref_id, lib_id)
    if not libs:
        return 0

    # Twins share a library, a normalized title and a year (_is_twin; two
    # rows never share a tmdb_id, it is unique), so bucket on that instead of
    # comparing every pair.
    buckets: dict[tuple, list[Movie]] = {}
    for m in db.scalars(select(Movie).where(Movie.year.is_not(None))).all():
        if m.id not in libs:
            continue
        buckets.setdefault((libs[m.id], _normalize_title(m.title or ""), m.year), []).append(m)

    deleted = 0
    for group in buckets.values():
        if len(group) < 2:
            continue
        group.sort(key=_rank)
        merged: set[uuid.UUID] = set()
        for i, primary in enumerate(group):
            if primary.id in merged:
                continue
            for secondary in group[i + 1:]:
                if secondary.id in merged or not _is_twin(primary, secondary):
                    continue
                _fold(db, primary, secondary)
                merged.add(secondary.id)
                deleted += 1

    if deleted:
        db.commit()
    return deleted


def _fold(db: Session, primary: Movie, secondary: Movie) -> None:
    """Move everything of `secondary` onto `primary`, then delete it."""
    from app.models.art import ArtOverride
    from app.models.collection import CollectionItem
    from app.models.metadata_lock import MetadataLock
    from app.models.playback import WatchHistory

    log.info(
        "merging twin movies: %s (%s) into %s (%s)",
        secondary.title, secondary.id, primary.title, primary.id,
    )

    # One admin-pinned version per movie: the primary's pin wins.
    if db.scalar(select(MediaFile.id).where(
        MediaFile.kind == MediaKind.movie, MediaFile.ref_id == primary.id,
        MediaFile.is_preferred_version.is_(True),
    ).limit(1)) is not None:
        db.execute(
            update(MediaFile)
            .where(MediaFile.kind == MediaKind.movie, MediaFile.ref_id == secondary.id)
            .values(is_preferred_version=None)
        )

    # Move the secondary's files to the primary (ids unchanged).
    db.execute(
        update(MediaFile)
        .where(MediaFile.kind == MediaKind.movie, MediaFile.ref_id == secondary.id)
        .values(ref_id=primary.id)
    )
    # History rows carry the movie id to relink a deleted file later.
    db.execute(
        update(WatchHistory)
        .where(WatchHistory.ref_kind == MediaKind.movie.value, WatchHistory.ref_id == secondary.id)
        .values(ref_id=primary.id)
    )

    # Admin overrides: keep the primary's, add the secondary's other keys.
    if secondary.overrides:
        combined = {**dict(secondary.overrides), **dict(primary.overrides or {})}
        if combined != (primary.overrides or {}):
            primary.overrides = combined

    # Metadata locks: move the ones the primary doesn't already have.
    primary_locked = set(db.scalars(
        select(MetadataLock.field_name).where(
            MetadataLock.entity_kind == "movie",
            MetadataLock.entity_id == primary.id,
        )
    ).all())
    for lock in db.scalars(
        select(MetadataLock).where(
            MetadataLock.entity_kind == "movie",
            MetadataLock.entity_id == secondary.id,
        )
    ).all():
        if lock.field_name not in primary_locked:
            db.add(MetadataLock(
                id=uuid.uuid4(),
                entity_kind="movie",
                entity_id=primary.id,
                field_name=lock.field_name,
                locked_at=lock.locked_at,
            ))
    db.execute(
        delete(MetadataLock).where(
            MetadataLock.entity_kind == "movie",
            MetadataLock.entity_id == secondary.id,
        )
    )

    # Art: drop the secondary's where the primary has its own, move the rest.
    primary_art_roles = set(db.scalars(
        select(ArtOverride.role).where(
            ArtOverride.entity_kind == "movie", ArtOverride.entity_id == primary.id,
        )
    ).all())
    if primary_art_roles:
        db.execute(
            delete(ArtOverride).where(
                ArtOverride.entity_kind == "movie",
                ArtOverride.entity_id == secondary.id,
                ArtOverride.role.in_(primary_art_roles),
            )
        )
    db.execute(
        update(ArtOverride)
        .where(ArtOverride.entity_kind == "movie", ArtOverride.entity_id == secondary.id)
        .values(entity_id=primary.id)
    )

    # Collection memberships: move, unless the primary is already in it.
    primary_cols = set(db.scalars(
        select(CollectionItem.collection_id).where(
            CollectionItem.entity_kind == "movie", CollectionItem.entity_id == primary.id,
        )
    ).all())
    if primary_cols:
        db.execute(
            delete(CollectionItem).where(
                CollectionItem.entity_kind == "movie",
                CollectionItem.entity_id == secondary.id,
                CollectionItem.collection_id.in_(primary_cols),
            )
        )
    db.execute(
        update(CollectionItem)
        .where(
            CollectionItem.entity_kind == "movie",
            CollectionItem.entity_id == secondary.id,
        )
        .values(entity_id=primary.id)
    )

    db.delete(secondary)
    db.flush()
