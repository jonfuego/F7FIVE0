"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-17

Covers the full Phase 1 data model:
  - identity (users, sessions, auth_events)
  - libraries
  - canonical metadata (movies, series, seasons, episodes,
                        artists, albums, tracks, music_videos)
  - media_files (polymorphic bridge to disk)
  - playback (watch_progress, watch_history)
  - transcoding (transcode_sessions, transcode_cache)
  - share_links
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Enums ----------------------------------------------------------
    # Create the TYPE up front with checkfirst=True (idempotent), then
    # reference them in columns with create_type=False so the table DDL
    # hook doesn't try to re-issue CREATE TYPE (which would fail).
    postgresql.ENUM("admin", "member", name="user_role").create(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(
        "movies", "tv", "music", "music_videos", name="library_kind"
    ).create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "movie", "episode", "track", "music_video", name="media_kind"
    ).create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "pending", "ready", "missing", "error", name="scan_state"
    ).create(op.get_bind(), checkfirst=True)

    user_role = postgresql.ENUM(
        "admin", "member", name="user_role", create_type=False
    )
    library_kind = postgresql.ENUM(
        "movies", "tv", "music", "music_videos",
        name="library_kind", create_type=False,
    )
    media_kind = postgresql.ENUM(
        "movie", "episode", "track", "music_video",
        name="media_kind", create_type=False,
    )
    scan_state = postgresql.ENUM(
        "pending", "ready", "missing", "error",
        name="scan_state", create_type=False,
    )

    # ---- users ----------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- sessions (refresh tokens) --------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("device_label", sa.String(120)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_user_active", "sessions", ["user_id", "revoked_at"])

    # ---- auth_events ----------------------------------------------------
    op.create_table(
        "auth_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("ip", postgresql.INET),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_events_user_id", "auth_events", ["user_id"])
    op.create_index("ix_auth_events_at", "auth_events", ["at"])
    op.create_index("ix_auth_events_user_at", "auth_events", ["user_id", "at"])

    # ---- libraries ------------------------------------------------------
    op.create_table(
        "libraries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", library_kind, nullable=False),
        sa.Column("root_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # ---- movies ---------------------------------------------------------
    op.create_table(
        "movies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tmdb_id", sa.Integer, unique=True),
        sa.Column("imdb_id", sa.String(32), unique=True),
        sa.Column("radarr_id", sa.Integer, unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("year", sa.Integer),
        sa.Column("overview", sa.Text),
        sa.Column("runtime_min", sa.Integer),
        sa.Column("poster_path", sa.String(1024)),
        sa.Column("backdrop_path", sa.String(1024)),
        sa.Column("genres", postgresql.JSONB),
        sa.Column("added_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_movies_tmdb_id", "movies", ["tmdb_id"], unique=True)
    op.create_index("ix_movies_imdb_id", "movies", ["imdb_id"], unique=True)
    op.create_index("ix_movies_radarr_id", "movies", ["radarr_id"], unique=True)
    op.create_index("ix_movies_title", "movies", ["title"])
    op.create_index("ix_movies_title_year", "movies", ["title", "year"])

    # ---- series / seasons / episodes -----------------------------------
    op.create_table(
        "series",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tvdb_id", sa.Integer, unique=True),
        sa.Column("tmdb_id", sa.Integer, unique=True),
        sa.Column("sonarr_id", sa.Integer, unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("overview", sa.Text),
        sa.Column("poster_path", sa.String(1024)),
        sa.Column("backdrop_path", sa.String(1024)),
        sa.Column("first_aired", sa.Date),
        sa.Column("added_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_series_tvdb_id", "series", ["tvdb_id"], unique=True)
    op.create_index("ix_series_tmdb_id", "series", ["tmdb_id"], unique=True)
    op.create_index("ix_series_sonarr_id", "series", ["sonarr_id"], unique=True)
    op.create_index("ix_series_title", "series", ["title"])

    op.create_table(
        "seasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_number", sa.Integer, nullable=False),
        sa.Column("poster_path", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("series_id", "season_number", name="uq_seasons_series_num"),
    )
    op.create_index("ix_seasons_series_id", "seasons", ["series_id"])

    op.create_table(
        "episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_number", sa.Integer, nullable=False),
        sa.Column("episode_number", sa.Integer, nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("overview", sa.Text),
        sa.Column("air_date", sa.Date),
        sa.Column("tvdb_id", sa.Integer, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "series_id", "season_number", "episode_number",
            name="uq_episodes_series_season_ep",
        ),
    )
    op.create_index("ix_episodes_series_id", "episodes", ["series_id"])
    op.create_index("ix_episodes_tvdb_id", "episodes", ["tvdb_id"], unique=True)
    op.create_index("ix_episodes_series_season", "episodes", ["series_id", "season_number"])

    # ---- artists / albums / tracks / music_videos ----------------------
    op.create_table(
        "artists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mbid", sa.String(64), unique=True),
        sa.Column("lidarr_id", sa.Integer, unique=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("overview", sa.Text),
        sa.Column("image_path", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_artists_mbid", "artists", ["mbid"], unique=True)
    op.create_index("ix_artists_lidarr_id", "artists", ["lidarr_id"], unique=True)
    op.create_index("ix_artists_name", "artists", ["name"])

    op.create_table(
        "albums",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("artist_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mbid", sa.String(64), unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("release_date", sa.Date),
        sa.Column("cover_path", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_albums_artist_id", "albums", ["artist_id"])
    op.create_index("ix_albums_mbid", "albums", ["mbid"], unique=True)
    op.create_index("ix_albums_title", "albums", ["title"])

    op.create_table(
        "tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("album_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("albums.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mbid", sa.String(64), unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("track_number", sa.Integer),
        sa.Column("disc_number", sa.Integer, server_default="1"),
        sa.Column("duration_sec", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "album_id", "disc_number", "track_number",
            name="uq_tracks_album_disc_track",
        ),
    )
    op.create_index("ix_tracks_album_id", "tracks", ["album_id"])
    op.create_index("ix_tracks_mbid", "tracks", ["mbid"], unique=True)
    op.create_index("ix_tracks_title", "tracks", ["title"])

    op.create_table(
        "music_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("artist_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("year", sa.Integer),
        sa.Column("thumb_path", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_music_videos_artist_id", "music_videos", ["artist_id"])
    op.create_index("ix_music_videos_title", "music_videos", ["title"])
    op.create_index("ix_music_videos_artist_year", "music_videos", ["artist_id", "year"])

    # ---- media_files ----------------------------------------------------
    op.create_table(
        "media_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", media_kind, nullable=False),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False, unique=True),
        sa.Column("container", sa.String(32)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("video_codec", sa.String(32)),
        sa.Column("audio_codec", sa.String(32)),
        sa.Column("audio_channels", sa.Integer),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("duration_sec", sa.Integer),
        sa.Column("bitrate_kbps", sa.Integer),
        sa.Column("probed_at", sa.DateTime(timezone=True)),
        sa.Column("scan_state", scan_state, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(width IS NULL AND height IS NULL) OR (width > 0 AND height > 0)",
            name="ck_media_files_dims_positive",
        ),
    )
    op.create_index("ix_media_files_kind_ref", "media_files", ["kind", "ref_id"])
    op.create_index("ix_media_files_scan_state", "media_files", ["scan_state"])

    # ---- watch_progress ------------------------------------------------
    op.create_table(
        "watch_progress",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("media_files.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position_sec", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_sec", sa.Integer),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_watch_progress_user_updated", "watch_progress", ["user_id", "updated_at"]
    )

    # ---- watch_history --------------------------------------------------
    op.create_table(
        "watch_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("last_position_sec", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_watch_history_user_id", "watch_history", ["user_id"])
    op.create_index("ix_watch_history_media_file_id", "watch_history", ["media_file_id"])
    op.create_index(
        "ix_watch_history_user_started", "watch_history", ["user_id", "started_at"]
    )

    # ---- transcode_sessions / transcode_cache --------------------------
    op.create_table(
        "transcode_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant", sa.String(32), nullable=False),
        sa.Column("direct_play", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("bytes_served", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_transcode_sessions_user_id", "transcode_sessions", ["user_id"])
    op.create_index("ix_transcode_sessions_media_file_id", "transcode_sessions", ["media_file_id"])

    op.create_table(
        "transcode_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant", sa.String(32), nullable=False),
        sa.Column("segment_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("media_file_id", "variant",
                            name="uq_transcode_cache_file_variant"),
    )
    op.create_index("ix_transcode_cache_last_access", "transcode_cache", ["last_access_at"])

    # ---- share_links ----------------------------------------------------
    op.create_table(
        "share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer),
        sa.Column("used_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_share_links_media_file_id", "share_links", ["media_file_id"])


def downgrade() -> None:
    # Drop in reverse creation order to respect FKs.
    op.drop_table("share_links")
    op.drop_table("transcode_cache")
    op.drop_table("transcode_sessions")
    op.drop_table("watch_history")
    op.drop_table("watch_progress")
    op.drop_table("media_files")
    op.drop_table("music_videos")
    op.drop_table("tracks")
    op.drop_table("albums")
    op.drop_table("artists")
    op.drop_table("episodes")
    op.drop_table("seasons")
    op.drop_table("series")
    op.drop_table("movies")
    op.drop_table("libraries")
    op.drop_table("auth_events")
    op.drop_table("sessions")
    op.drop_table("users")

    for name in ("scan_state", "media_kind", "library_kind", "user_role"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
