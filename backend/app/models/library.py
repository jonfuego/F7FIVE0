"""Logical library buckets."""
from __future__ import annotations

import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class LibraryKind(str, enum.Enum):
    movies = "movies"
    tv = "tv"
    music = "music"
    music_videos = "music_videos"


class Library(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "libraries"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[LibraryKind] = mapped_column(
        Enum(LibraryKind, name="library_kind"),
        nullable=False,
    )
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
