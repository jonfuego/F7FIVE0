"""Movie version management: merge twin movies in the same library.

A "twin" is a second Movie row created by the folder scan for a file in a
different folder that matches an existing movie by tmdb_id (or by the same
normalized title and year). Twins in the SAME library become additional
media_files rows on the primary movie; twins in DIFFERENT libraries stay
separate entries per Jon's decision (2026-10-18).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.media_file import MediaFile, MediaKind
from app.models.movie import Movie

log = logging.getLogger("f7five0.movie_versions")


def _normalize_title(title: str) -> str:
    """Lowercase, strip leading 'the '/'a '/'an ', collapse whitespace."""
    import re
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


def merge_twins(db: Session) -> int:
    """For each pair of twins in the same library, fold the secondary into the
    primary. Media file ids never change, so watch history keyed by file stays.
    Movies in different libraries are never merged.
    Returns the number of movie rows deleted (the merged twins).
    """
    from app.models.art import ArtOverride
    from app.models.metadata_lock import MetadataLock
    from app.models.collection import CollectionItem

    movies = db.scalars(select(Movie)).all()
    deleted = 0

    # Group by library_id. Only merge within the same library.
    # A movie's "library" is the library_id on its media files.
    # We find the library_id from the first ready media file.
    def library_of(movie: Movie) -> Optional[uuid.UUID]:
        mf = db.scalar(
            select(MediaFile.library_id).where(
                MediaFile.kind == MediaKind.movie,
                MediaFile.ref_id == movie.id,
            ).limit(1)
        )
        return mf

    # Build a list of (movie, library_id) pairs
    movie_libs: list[tuple[Movie, Optional[uuid.UUID]]] = []
    for m in movies:
        lib = library_of(m)
        movie_libs.append((m, lib))

    # Group movies by library
    by_lib: dict[Optional[uuid.UUID], list[Movie]] = {}
    for m, lib in movie_libs:
        by_lib.setdefault(lib, []).append(m)

    merged_ids: set[uuid.UUID] = set()

    for lib_id, lib_movies in by_lib.items():
        # Find twin pairs within this library
        for i, primary in enumerate(lib_movies):
            if primary.id in merged_ids:
                continue
            for secondary in lib_movies[i + 1:]:
                if secondary.id in merged_ids:
                    continue
                if not _is_twin(primary, secondary):
                    continue

                # Determine which is primary (prefer the one with tmdb_id)
                if secondary.tmdb_id and not primary.tmdb_id:
                    primary, secondary = secondary, primary

                log.info(
                    "merging twin movies: %s (%s) into %s (%s)",
                    secondary.title, secondary.id, primary.title, primary.id,
                )

                # Move secondary's media_files to primary
                db.execute(
                    update(MediaFile)
                    .where(MediaFile.kind == MediaKind.movie, MediaFile.ref_id == secondary.id)
                    .values(ref_id=primary.id)
                )

                # Move metadata_locks for fields primary doesn't already have
                primary_locked = set(db.scalars(
                    select(MetadataLock.field_name).where(
                        MetadataLock.entity_kind == "movie",
                        MetadataLock.entity_id == primary.id,
                    )
                ).all())
                sec_locks = db.scalars(
                    select(MetadataLock).where(
                        MetadataLock.entity_kind == "movie",
                        MetadataLock.entity_id == secondary.id,
                    )
                ).all()
                for lock in sec_locks:
                    if lock.field_name not in primary_locked:
                        db.add(MetadataLock(
                            id=uuid.uuid4(),
                            entity_kind="movie",
                            entity_id=primary.id,
                            field_name=lock.field_name,
                            locked_at=lock.locked_at,
                        ))

                # Delete secondary's art rows only where primary already has its own
                primary_art_roles = set(db.scalars(
                    select(ArtOverride.role).where(ArtOverride.entity_id == primary.id)
                ).all())
                db.execute(
                    delete(ArtOverride).where(
                        ArtOverride.entity_id == secondary.id,
                        ArtOverride.role.in_(primary_art_roles),
                    )
                )

                # Move remaining secondary art to primary
                db.execute(
                    update(ArtOverride)
                    .where(ArtOverride.entity_id == secondary.id)
                    .values(entity_id=primary.id)
                )

                # Update collection_items pointing at secondary
                db.execute(
                    update(CollectionItem)
                    .where(
                        CollectionItem.entity_kind == "movie",
                        CollectionItem.entity_id == secondary.id,
                    )
                    .values(entity_id=primary.id)
                )

                # Delete secondary's metadata locks
                db.execute(
                    delete(MetadataLock).where(
                        MetadataLock.entity_kind == "movie",
                        MetadataLock.entity_id == secondary.id,
                    )
                )

                # Delete the secondary movie row
                db.delete(secondary)
                db.flush()
                merged_ids.add(secondary.id)
                deleted += 1

    if deleted:
        db.commit()
    return deleted
