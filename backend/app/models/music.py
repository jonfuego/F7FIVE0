"""Artist / Album / Track / MusicVideo: mirrored from Lidarr."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class Artist(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "artists"

    mbid: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    lidarr_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Optional per-row sort override. When null the list endpoints fall
    # back to article-stripped lowercase name (see _sort_key in api/library.py).
    sort_name: Mapped[Optional[str]] = mapped_column(String(255))
    overview: Mapped[Optional[str]] = mapped_column(Text)
    image_path: Mapped[Optional[str]] = mapped_column(String(1024))
    genres: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )

    # MusicBrainz + Wikipedia enrichment
    country: Mapped[Optional[str]] = mapped_column(String(8))
    artist_type: Mapped[Optional[str]] = mapped_column(String(32))
    formed_year: Mapped[Optional[int]] = mapped_column(Integer)
    disbanded_year: Mapped[Optional[int]] = mapped_column(Integer)
    links: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    bio_text: Mapped[Optional[str]] = mapped_column(Text)
    bio_source: Mapped[Optional[str]] = mapped_column(String(32))
    metadata_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    metadata_status: Mapped[Optional[str]] = mapped_column(String(32))

    # Per-row admin overrides applied at the response-serializer boundary.
    # Keys: display_name, tagline, year, rating. Sort name has its own
    # column above.
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )

    albums: Mapped[list["Album"]] = relationship(
        back_populates="artist",
        cascade="all, delete-orphan",
    )
    music_videos: Mapped[list["MusicVideo"]] = relationship(
        back_populates="artist",
        cascade="all, delete-orphan",
    )
    music_video_releases: Mapped[list["MusicVideoRelease"]] = relationship(
        back_populates="artist",
        cascade="all, delete-orphan",
    )


class Album(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "albums"

    artist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mbid: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Optional per-row sort override; same shape as movies/series sort_title.
    sort_title: Mapped[Optional[str]] = mapped_column(String(255))
    release_date: Mapped[Optional[date]] = mapped_column(Date)
    cover_path: Mapped[Optional[str]] = mapped_column(String(1024))
    genres: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )

    # MusicBrainz + Lidarr enrichment
    album_type: Mapped[Optional[str]] = mapped_column(String(32))
    secondary_types: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    label: Mapped[Optional[str]] = mapped_column(String(256))
    disambiguation: Mapped[Optional[str]] = mapped_column(Text)
    mb_rating: Mapped[Optional[float]] = mapped_column(Float)
    links: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    metadata_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    metadata_status: Mapped[Optional[str]] = mapped_column(String(32))

    # Per-row admin overrides; see Artist.overrides.
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )

    artist: Mapped["Artist"] = relationship(back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship(
        back_populates="album",
        cascade="all, delete-orphan",
    )


class Track(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tracks"

    album_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("albums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mbid: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Optional per-row sort override; same shape as albums.sort_title.
    sort_title: Mapped[Optional[str]] = mapped_column(String(255))
    track_number: Mapped[Optional[int]] = mapped_column(Integer)
    disc_number: Mapped[Optional[int]] = mapped_column(Integer, default=1)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)

    # Per-row admin overrides; see Artist.overrides.
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )

    album: Mapped["Album"] = relationship(back_populates="tracks")

    __table_args__ = (
        UniqueConstraint(
            "album_id", "disc_number", "track_number",
            name="uq_tracks_album_disc_track",
        ),
    )


class MusicVideoRelease(UUIDPKMixin, TimestampMixin, Base):
    """One release (album, EP, concert film, single) under an artist.

    Mirrors the `Series → Season → Episode` shape: an artist owns many
    releases, a release owns many videos. Multi-disc releases are stored
    as a single release with `disc_number` on the child videos.
    """

    __tablename__ = "music_video_releases"

    artist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # MusicBrainz release-group id. Set by Fix Match when an admin re-attaches
    # a wrongly-matched release. Nullable because the filesystem-driven scan
    # does not assign one on first ingest.
    mbid: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    release_year: Mapped[Optional[int]] = mapped_column(Integer)
    release_date: Mapped[Optional[date]] = mapped_column(Date)
    cover_path: Mapped[Optional[str]] = mapped_column(String(1024))
    # POSIX-style relative path from the artist folder, e.g.
    # "Brotherhood - Definitive Edition DVD 1 & 2". One row per first-level
    # subfolder under the artist.
    source_subpath: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Per-row sort overrides; null falls back to algorithmic article-strip
    # on title and to release_year for the year axis. See _sort_expr in
    # api/library.py.
    sort_title: Mapped[Optional[str]] = mapped_column(String(255))
    sort_year: Mapped[Optional[int]] = mapped_column(Integer)

    # Per-row admin overrides; see Artist.overrides.
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )

    artist: Mapped["Artist"] = relationship(back_populates="music_video_releases")
    videos: Mapped[list["MusicVideo"]] = relationship(
        back_populates="release",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "ux_music_video_releases_artist_subpath",
            "artist_id", "source_subpath",
            unique=True,
        ),
        Index(
            "ux_music_video_releases_mbid",
            "mbid",
            unique=True,
            postgresql_where=text("mbid IS NOT NULL"),
        ),
    )


class MusicVideo(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "music_videos"

    # release_id is the new parent. artist_id is kept denormalized so legacy
    # query paths don't break atomically; new code reads `release.artist_id`.
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("music_video_releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    thumb_path: Mapped[Optional[str]] = mapped_column(String(1024))
    # POSIX-style path under the release folder. Disc-folder segment is
    # stripped during scan and surfaced via disc_number instead, so this
    # value never starts with "Disc 01/".
    source_subpath: Mapped[Optional[str]] = mapped_column(String(1024))
    disc_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    track_number: Mapped[Optional[int]] = mapped_column(Integer)
    # Per-video sort override. Null falls back to algorithmic article-strip.
    sort_title: Mapped[Optional[str]] = mapped_column(String(255))

    artist: Mapped["Artist"] = relationship(back_populates="music_videos")
    release: Mapped["MusicVideoRelease"] = relationship(back_populates="videos")

    __table_args__ = (
        Index(
            "ix_music_videos_release_disc_track",
            "release_id", "disc_number", "track_number",
        ),
    )
