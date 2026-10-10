"""Merge one artist into another, durably, with undo.

An admin merges a collaboration-credit artist (for example "2Pac Featuring KC
And Jojo") into the main artist ("2Pac"). This:

  1. Moves the source artist's albums and tracks to the target.
  2. Saves an alias (artist_aliases) so the folder scan and the Lidarr sync
     resolve the source name and MBID to the target and do not recreate it.
  3. Records the merge (artist_merges) with enough of the source artist to
     restore it, so the merge can be undone.
  4. Deletes the source artist row.

Undo removes the alias, recreates the source artist from the record, moves the
albums that moved back onto it, and marks the merge undone. Album.credited_as /
Track.credited_as are left in place either way so the record of who was on each
release survives both the merge and the undo.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.music import Album, Artist, ArtistAlias, ArtistMerge, Track


log = logging.getLogger("f7five0.artist_merge")

# Artist columns copied into the merge record so undo can rebuild the source.
_SNAPSHOT_FIELDS = (
    "name", "mbid", "lidarr_id", "sort_name", "overview", "image_path",
    "genres", "country", "artist_type", "formed_year", "disbanded_year",
    "links", "bio_text", "bio_source", "overrides",
)


class MergeError(Exception):
    """A merge or undo that cannot proceed (bad ids, same source and target)."""


def preview(db: Session, source: Artist) -> dict:
    """How much moves: album and track counts under the source artist.

    Used by the confirm dialog so it can name what the merge moves.
    """
    album_count = db.scalar(
        select(func.count(Album.id)).where(Album.artist_id == source.id)
    ) or 0
    track_count = db.scalar(
        select(func.count(Track.id))
        .join(Album, Album.id == Track.album_id)
        .where(Album.artist_id == source.id)
    ) or 0
    return {"albums": int(album_count), "tracks": int(track_count)}


def _snapshot(artist: Artist) -> dict:
    out: dict = {}
    for field in _SNAPSHOT_FIELDS:
        value = getattr(artist, field, None)
        out[field] = list(value) if isinstance(value, list) else (
            dict(value) if isinstance(value, dict) else value
        )
    return out


def merge(db: Session, source: Artist, target: Artist) -> ArtistMerge:
    """Move source's albums and tracks to target, alias the source, and record
    the merge so it can be undone. Does not commit; the caller does."""
    if source.id == target.id:
        raise MergeError("cannot merge an artist into itself")

    counts = preview(db, source)
    album_ids = list(db.scalars(
        select(Album.id).where(Album.artist_id == source.id)
    ))

    # Keep who was on each record. An album / track that had no explicit credit
    # yet gets the source artist's name stamped as its credited_as, so after the
    # merge the album still shows "2Pac Featuring KC And Jojo" and not just the
    # target name.
    if album_ids:
        for track in db.scalars(
            select(Track).where(Track.album_id.in_(album_ids))
        ):
            if not track.credited_as:
                track.credited_as = source.name
    for album in db.scalars(select(Album).where(Album.artist_id == source.id)):
        if not album.credited_as:
            album.credited_as = source.name
        album.artist_id = target.id

    record = ArtistMerge(
        target_artist_id=target.id,
        source_name=source.name,
        source_mbid=source.mbid,
        source_snapshot=_snapshot(source),
        moved_album_ids=[str(a) for a in album_ids],
    )
    db.add(record)

    # The durable alias: name and MBID both route to the target on the next
    # scan / sync. A name_key already aliased elsewhere is overwritten to point
    # at the new target (a re-merge of the same name).
    _upsert_alias(
        db, target_id=target.id, source_name=source.name,
        source_mbid=source.mbid,
    )

    db.delete(source)
    db.flush()
    log.info(
        "merged artist %r into %r: %d albums, %d tracks",
        record.source_name, target.name, counts["albums"], counts["tracks"],
    )
    return record


def undo(db: Session, record: ArtistMerge) -> Artist:
    """Reverse a merge: recreate the source artist, move its albums back, drop
    the alias. Does not commit; the caller does."""
    if record.undone_at is not None:
        raise MergeError("this merge has already been undone")

    snap = dict(record.source_snapshot or {})
    # A source MBID / name that is now taken by another row (a rescan created a
    # fresh collision, say) would violate the unique constraint. Drop a colliding
    # mbid rather than fail the undo; the name is kept.
    mbid = snap.get("mbid")
    if mbid and db.scalar(select(Artist.id).where(Artist.mbid == mbid)) is not None:
        log.warning("source mbid %s is taken; restoring artist without it", mbid)
        mbid = None
    lidarr_id = snap.get("lidarr_id")
    if lidarr_id is not None and db.scalar(
        select(Artist.id).where(Artist.lidarr_id == lidarr_id)
    ) is not None:
        lidarr_id = None

    restored = Artist(
        name=snap.get("name") or record.source_name or "Unknown Artist",
        mbid=mbid,
        lidarr_id=lidarr_id,
        sort_name=snap.get("sort_name"),
        overview=snap.get("overview"),
        image_path=snap.get("image_path"),
        genres=snap.get("genres") or [],
        country=snap.get("country"),
        artist_type=snap.get("artist_type"),
        formed_year=snap.get("formed_year"),
        disbanded_year=snap.get("disbanded_year"),
        links=snap.get("links") or [],
        bio_text=snap.get("bio_text"),
        bio_source=snap.get("bio_source"),
        overrides=snap.get("overrides") or {},
    )
    db.add(restored)
    db.flush()

    moved = [uuid.UUID(a) if isinstance(a, str) else a for a in (record.moved_album_ids or [])]
    for album in db.scalars(select(Album).where(Album.id.in_(moved))):
        album.artist_id = restored.id

    # Remove the alias(es) that pointed the source at the target.
    for alias in db.scalars(select(ArtistAlias).where(
        ArtistAlias.name_key == (record.source_name or "").lower(),
        ArtistAlias.target_artist_id == record.target_artist_id,
    )):
        db.delete(alias)
    if record.source_mbid:
        for alias in db.scalars(select(ArtistAlias).where(
            ArtistAlias.source_mbid == record.source_mbid,
            ArtistAlias.target_artist_id == record.target_artist_id,
        )):
            db.delete(alias)

    record.undone_at = datetime.now(timezone.utc)
    db.flush()
    log.info("undid merge of %r, restored %d albums", record.source_name, len(moved))
    return restored


def _upsert_alias(
    db: Session, *, target_id: uuid.UUID, source_name: str,
    source_mbid: Optional[str],
) -> ArtistAlias:
    name_key = (source_name or "").lower()
    alias = db.scalar(
        select(ArtistAlias).where(ArtistAlias.name_key == name_key)
    )
    if alias is None and source_mbid:
        alias = db.scalar(
            select(ArtistAlias).where(ArtistAlias.source_mbid == source_mbid)
        )
    if alias is None:
        alias = ArtistAlias(
            target_artist_id=target_id, name_key=name_key,
            source_name=source_name, source_mbid=source_mbid,
        )
        db.add(alias)
    else:
        alias.target_artist_id = target_id
        alias.name_key = name_key
        alias.source_name = source_name
        alias.source_mbid = source_mbid
    db.flush()
    return alias
