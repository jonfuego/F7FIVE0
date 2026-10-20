"""Named libraries, their source folders, and per-user access.

A library is a named group of folders of one kind (movies, TV, music, music
videos, podcasts). There can be more than one library per kind. Each media file
is stamped with the id of the library whose folder it came from
(`media_files.library_id`), so an item's library membership is the set of
libraries of its files.

Access is a deny-list: `user_library_access` holds one row per (user, library)
that an admin has hidden from that user. No row means the library is visible;
admins see every library. The central helper is `app/services/library_access.py`.

`root_path` on `libraries` is the legacy one-folder-per-row column, kept nullable
so the 0030 migration is non-destructive; `library_folders` is the authoritative
folder source for all new code (see `app/services/library_folders.py`).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin, utcnow


class LibraryKind(str, enum.Enum):
    movies = "movies"
    tv = "tv"
    music = "music"
    music_videos = "music_videos"
    podcasts = "podcasts"


class Library(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "libraries"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[LibraryKind] = mapped_column(
        Enum(LibraryKind, name="library_kind"),
        nullable=False,
    )
    # Legacy one-folder-per-row column. Nullable since 0030; folders now live in
    # `library_folders`. Kept unique-when-set so the pre-0030 rows migrate cleanly.
    root_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, unique=True)
    # Display order within a kind (lower first). Default 0.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Reserved for phase-4 per-library settings (naming templates, etc.). Only
    # access/name/sort are read in phase 1.
    settings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class LibraryFolder(UUIDPKMixin, Base):
    __tablename__ = "library_folders"

    library_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("libraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow,
    )

    __table_args__ = (
        Index("ix_library_folders_library", "library_id"),
    )


class UserLibraryAccess(UUIDPKMixin, Base):
    """A row means the library is hidden from that user (deny-list)."""

    __tablename__ = "user_library_access"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    library_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("libraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "library_id", name="uq_user_library_access"),
        Index("ix_user_library_access_user", "user_id"),
    )
