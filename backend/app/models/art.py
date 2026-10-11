"""ArtOverride: admin-selected art for an entity, stored on local disk.

One row per (entity_kind, entity_id, role). Exists to survive remote URLs
going 404 and to let the admin pick a specific image when the library
source picked a bad one.

The read path checks this table first and only falls through to the
entity's native column (e.g. Movie.poster_path) when no override exists.
Native columns keep being populated by *arr sync so removing an override
cleanly restores whatever the sync had picked.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# entity_kind values.
ENTITY_ARTIST = "artist"
ENTITY_ALBUM = "album"
ENTITY_MOVIE = "movie"
ENTITY_SERIES = "series"
ENTITY_MUSIC_VIDEO = "music_video"
ENTITY_MIX = "mix"

# role values.
ROLE_THUMB = "thumb"
ROLE_POSTER = "poster"
ROLE_BACKDROP = "backdrop"
ROLE_COVER = "cover"

# source_kind values. Captured on write so a future "refresh art from the
# same source" feature doesn't need to ask the admin to re-pick.
SOURCE_UPLOAD = "upload"
SOURCE_URL = "url"
SOURCE_LIDARR = "lidarr"
SOURCE_RADARR = "radarr"
SOURCE_SONARR = "sonarr"
SOURCE_FANART = "fanart"
SOURCE_MUSICBRAINZ = "musicbrainz"
# An artist picture the background auto-fill job found (TheAudioDB or Deezer)
# for an artist that had no thumb at all. Like the music-video `frame` grab it
# is the weakest art there is: any other art replaces it, and it never
# replaces anything. Written only by services/artist_art_autofill.py.
SOURCE_ARTIST_AUTO = "artist_auto"


class ArtOverride(Base):
    __tablename__ = "art_overrides"

    entity_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)

    # Path relative to settings.art_root. Example:
    # "artist/<uuid>/thumb.jpg". Stored relative so the art_root can be
    # relocated without a data migration.
    local_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(2048))

    set_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_art_overrides_entity", "entity_kind", "entity_id"),
    )
