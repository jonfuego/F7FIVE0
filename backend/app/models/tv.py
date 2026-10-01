"""Series / Season / Episode: mirrored from Sonarr."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin


class Series(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "series"

    tvdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    sonarr_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Optional per-row sort override. When null the list endpoints fall
    # back to article-stripped lowercase title (see _sort_key in api/library.py).
    sort_title: Mapped[Optional[str]] = mapped_column(String(255))
    overview: Mapped[Optional[str]] = mapped_column(Text)
    poster_path: Mapped[Optional[str]] = mapped_column(String(1024))
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(1024))
    first_aired: Mapped[Optional[date]] = mapped_column(Date)
    added_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Per-row admin overrides; see Movie.overrides.
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )

    seasons: Mapped[list["Season"]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
    )
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
    )


class Season(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "seasons"

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    poster_path: Mapped[Optional[str]] = mapped_column(String(1024))

    series: Mapped["Series"] = relationship(back_populates="seasons")

    __table_args__ = (
        UniqueConstraint("series_id", "season_number", name="uq_seasons_series_num"),
    )


class Episode(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "episodes"

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512))
    overview: Mapped[Optional[str]] = mapped_column(Text)
    air_date: Mapped[Optional[date]] = mapped_column(Date)
    tvdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)

    series: Mapped["Series"] = relationship(back_populates="episodes")

    __table_args__ = (
        UniqueConstraint(
            "series_id", "season_number", "episode_number",
            name="uq_episodes_series_season_ep",
        ),
        Index("ix_episodes_series_season", "series_id", "season_number"),
    )
