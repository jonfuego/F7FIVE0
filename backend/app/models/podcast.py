"""Podcasts: shows, episodes, per-user subscriptions and per-user progress.

A show is either `feed` (it came from an RSS feed) or `local` (it was found in a
podcasts library folder and has no feed). An episode may have a file on the
server (`media_file_id`, a `podcast_episode` media file) and may have been put
there by F7FIVE0 itself (`downloaded_by_f7five0`), which is the only kind of
file Admin is allowed to remove. Subscriptions and progress are per user.

Show art lives in `art_overrides` (entity kind `podcast`, role `cover`) like
every other art; there is no art column here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, UUIDPKMixin

SOURCE_FEED = "feed"
SOURCE_LOCAL = "local"


class Podcast(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "podcasts"

    # NULL for a local-only show. Unique, so one feed is one show.
    feed_url: Mapped[Optional[str]] = mapped_column(String(2048), unique=True)
    podcast_guid: Mapped[Optional[str]] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(512))
    # Plain text only: tags are stripped and entities unescaped before storing.
    description: Mapped[Optional[str]] = mapped_column(Text)
    # The show's folder on the server (set by a download or a local scan).
    folder_path: Mapped[Optional[str]] = mapped_column(String(2048))
    etag: Mapped[Optional[str]] = mapped_column(String(512))
    last_modified: Mapped[Optional[str]] = mapped_column(String(128))
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=SOURCE_FEED)

    __table_args__ = (
        CheckConstraint("source IN ('feed', 'local')", name="ck_podcasts_source"),
        Index("ix_podcasts_folder_path", "folder_path"),
    )


class PodcastEpisode(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "podcast_episodes"

    podcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcasts.id", ondelete="CASCADE"), nullable=False,
    )
    # The feed's own guid, else the enclosure URL, else `local:<path>`.
    guid: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    enclosure_url: Mapped[Optional[str]] = mapped_column(String(2048))
    enclosure_type: Mapped[Optional[str]] = mapped_column(String(128))
    enclosure_length: Mapped[Optional[int]] = mapped_column(BigInteger)
    season: Mapped[Optional[int]] = mapped_column(Integer)
    episode: Mapped[Optional[int]] = mapped_column(Integer)
    chapters_url: Mapped[Optional[str]] = mapped_column(String(2048))
    # The normalised chapters fetched from `chapters_url`, cached.
    chapters_json: Mapped[Optional[Any]] = mapped_column(JSONB)
    media_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="SET NULL"),
    )
    downloaded_by_f7five0: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("podcast_id", "guid", name="uq_podcast_episodes_guid"),
        Index("ix_podcast_episodes_podcast_published", "podcast_id", "published_at"),
        Index("ix_podcast_episodes_media_file", "media_file_id"),
    )


class PodcastSubscription(Base):
    __tablename__ = "podcast_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    podcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcasts.id", ondelete="CASCADE"), primary_key=True,
    )
    auto_download: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (Index("ix_podcast_subscriptions_podcast", "podcast_id"),)


class PodcastEpisodeProgress(Base):
    __tablename__ = "podcast_episode_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_episodes.id", ondelete="CASCADE"), primary_key=True,
    )
    position_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    # Set when the episode counts as played (by the rule or by hand).
    played_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # When the device took the saved position (its own clock), so a save that
    # arrives late (an offline buffer replay, a retry) cannot replace a newer
    # one. Null for rows written before 0029 and by clients that do not send it.
    client_recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_podcast_progress_user_updated", "user_id", "updated_at"),)
