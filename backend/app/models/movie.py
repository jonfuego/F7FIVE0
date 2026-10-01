"""Movies: canonical metadata mirrored from Radarr."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class Movie(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "movies"

    # External IDs
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), unique=True, index=True)
    radarr_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)

    # Metadata
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Optional per-row sort override. When null the list endpoints fall
    # back to article-stripped lowercase title (see _sort_key in api/library.py).
    sort_title: Mapped[Optional[str]] = mapped_column(String(255))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    overview: Mapped[Optional[str]] = mapped_column(Text)
    runtime_min: Mapped[Optional[int]] = mapped_column(Integer)
    poster_path: Mapped[Optional[str]] = mapped_column(String(1024))
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(1024))
    genres: Mapped[Optional[list]] = mapped_column(JSONB)

    added_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # TMDB-sourced enrichment. `cast` is the column name in the database;
    # the Python attribute is `movie_cast` to dodge the SQL keyword + builtin.
    tagline: Mapped[Optional[str]] = mapped_column(Text)
    movie_cast: Mapped[list] = mapped_column(
        "cast",
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    directors: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    tmdb_rating: Mapped[Optional[float]] = mapped_column(Float)
    tmdb_vote_count: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    metadata_status: Mapped[Optional[str]] = mapped_column(String(32))

    # Per-row admin overrides applied at the response-serializer boundary.
    # Keys: display_name, tagline, year, runtime_min, rating.
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )

    __table_args__ = (
        Index("ix_movies_title_year", "title", "year"),
    )
