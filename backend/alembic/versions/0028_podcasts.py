"""podcasts: shows, episodes, subscriptions, progress

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-11

Adds the storage behind podcasts (release 1.0.11):

  - podcasts: one row per show, from an RSS feed or from a podcasts library
    folder (`source` feed | local). Descriptions are plain text.
  - podcast_episodes: one row per episode, unique per (podcast, guid), with the
    publisher's enclosure, optional chapters, and the link to a file on the
    server (media_file_id, downloaded_by_f7five0).
  - podcast_subscriptions: which user follows which show, and whether new
    episodes download to the server by themselves.
  - podcast_episode_progress: each user's position and played mark per episode.

It also adds the `podcasts` value to the `library_kind` enum (a new kind of
library folder) and the `podcast_episode` value to the `media_kind` enum (the
kind of a media file that holds an episode). PostgreSQL cannot run ALTER TYPE ...
ADD VALUE inside a transaction, so it runs in an autocommit block.

All additive. Downgrade drops the four new tables and leaves the two enum values
in place: PostgreSQL cannot remove a value from an enum, and an unused value is
harmless (running upgrade again adds it only if it is missing).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE library_kind ADD VALUE IF NOT EXISTS 'podcasts'")
        op.execute("ALTER TYPE media_kind ADD VALUE IF NOT EXISTS 'podcast_episode'")

    op.create_table(
        "podcasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("feed_url", sa.String(length=2048), nullable=True),
        sa.Column("podcast_guid", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("author", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("folder_path", sa.String(length=2048), nullable=True),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified", sa.String(length=128), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="feed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feed_url", name="uq_podcasts_feed_url"),
        sa.CheckConstraint("source IN ('feed', 'local')", name="ck_podcasts_source"),
    )
    op.create_index("ix_podcasts_folder_path", "podcasts", ["folder_path"])

    op.create_table(
        "podcast_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("podcast_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guid", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("enclosure_url", sa.String(length=2048), nullable=True),
        sa.Column("enclosure_type", sa.String(length=128), nullable=True),
        sa.Column("enclosure_length", sa.BigInteger(), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("chapters_url", sa.String(length=2048), nullable=True),
        sa.Column("chapters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("downloaded_by_f7five0", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["podcast_id"], ["podcasts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("podcast_id", "guid", name="uq_podcast_episodes_guid"),
    )
    op.create_index("ix_podcast_episodes_podcast_published", "podcast_episodes", ["podcast_id", "published_at"])
    op.create_index("ix_podcast_episodes_media_file", "podcast_episodes", ["media_file_id"])

    op.create_table(
        "podcast_subscriptions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("podcast_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auto_download", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["podcast_id"], ["podcasts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "podcast_id"),
    )
    op.create_index("ix_podcast_subscriptions_podcast", "podcast_subscriptions", ["podcast_id"])

    op.create_table(
        "podcast_episode_progress",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_sec", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_id"], ["podcast_episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "episode_id"),
    )
    op.create_index("ix_podcast_progress_user_updated", "podcast_episode_progress", ["user_id", "updated_at"])


def downgrade() -> None:
    # The `podcasts` value of library_kind and the `podcast_episode` value of
    # media_kind stay: PostgreSQL cannot drop an enum value.
    op.drop_index("ix_podcast_progress_user_updated", table_name="podcast_episode_progress")
    op.drop_table("podcast_episode_progress")
    op.drop_index("ix_podcast_subscriptions_podcast", table_name="podcast_subscriptions")
    op.drop_table("podcast_subscriptions")
    op.drop_index("ix_podcast_episodes_media_file", table_name="podcast_episodes")
    op.drop_index("ix_podcast_episodes_podcast_published", table_name="podcast_episodes")
    op.drop_table("podcast_episodes")
    op.drop_index("ix_podcasts_folder_path", table_name="podcasts")
    op.drop_table("podcasts")
