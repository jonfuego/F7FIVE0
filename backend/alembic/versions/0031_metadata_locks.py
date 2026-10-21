"""metadata_locks, watch_history reclaimability, missing_since

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-17

Adds the metadata_locks table (per-field editor locks), extends watch_history
and track_plays for orphan relinking (media_file_id / track_id become nullable
with SET NULL, new ref_kind/ref_id/last_path/ref_key columns), and adds
missing_since to media_files so the 7-day cleanup clock starts precisely at
the moment a file first goes missing (never at an arbitrary updated_at touch).
"""
from typing import Sequence, Union
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_context().dialect.name

    # 1. metadata_locks: per-field editor locks keyed by (entity_kind, entity_id, field_name).
    op.create_table(
        "metadata_locks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_kind", "entity_id", "field_name",
            name="uq_metadata_locks_kind_entity_field",
        ),
    )
    op.create_index(
        "ix_metadata_locks_entity",
        "metadata_locks",
        ["entity_kind", "entity_id"],
    )

    # 2. watch_history: make media_file_id nullable (SET NULL on file delete),
    #    add ref columns for orphan relinking.
    with op.batch_alter_table("watch_history") as batch:
        batch.alter_column(
            "media_file_id",
            existing_type=sa.String(36),
            nullable=True,
            existing_nullable=False,
        )
        if dialect == "postgresql":
            batch.drop_constraint("watch_history_media_file_id_fkey", type_="foreignkey")
            batch.create_foreign_key(
                "fk_watch_history_media_file",
                "media_files",
                ["media_file_id"],
                ["id"],
                ondelete="SET NULL",
            )
        batch.add_column(sa.Column("ref_kind", sa.String(32), nullable=True))
        batch.add_column(sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch.add_column(sa.Column("last_path", sa.String(2048), nullable=True))
        batch.add_column(sa.Column("ref_key", sa.String(128), nullable=True))

    # 3. track_plays: make track_id nullable (SET NULL on track delete),
    #    add last_path and ref_key for orphan relinking.
    with op.batch_alter_table("track_plays") as batch:
        batch.alter_column(
            "track_id",
            existing_type=sa.String(36),
            nullable=True,
            existing_nullable=False,
        )
        if dialect == "postgresql":
            batch.drop_constraint("track_plays_track_id_fkey", type_="foreignkey")
            batch.create_foreign_key(
                "fk_track_plays_track",
                "tracks",
                ["track_id"],
                ["id"],
                ondelete="SET NULL",
            )
        batch.add_column(sa.Column("last_path", sa.String(2048), nullable=True))
        batch.add_column(sa.Column("ref_key", sa.String(128), nullable=True))

    # 4. media_files: add missing_since so the 7-day cleanup clock is precise.
    with op.batch_alter_table("media_files") as batch:
        batch.add_column(
            sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True)
        )

    # 5. Data steps.
    _backfill(dialect)


# ids in the data steps. psycopg casts every bind to the type of the column it
# is given (`$1::VARCHAR` for sa.String), and PostgreSQL has no `uuid = varchar`
# operator and no varchar to uuid assignment, so ids must bind as uuid there. On
# SQLite the rows hold dashed text, which String(36) passes through as is
# (sa.Uuid would compare 32-char hex and miss them). as_uuid=False keeps ids as
# str on both sides. media_files.kind and scan_state are PostgreSQL enums with
# no `enum = varchar` operator either, so the steps compare them cast to text.
_UUID = postgresql.UUID(as_uuid=False).with_variant(sa.String(36), "sqlite")


def _backfill(dialect: str) -> None:
    bind = op.get_bind()

    watch_history = sa.table(
        "watch_history",
        sa.column("id", _UUID),
        sa.column("media_file_id", _UUID),
        sa.column("ref_kind", sa.String),
        sa.column("ref_id", _UUID),
        sa.column("last_path", sa.String),
        sa.column("ref_key", sa.String),
    )
    track_plays = sa.table(
        "track_plays",
        sa.column("id", _UUID),
        sa.column("track_id", _UUID),
        sa.column("last_path", sa.String),
        sa.column("ref_key", sa.String),
    )
    media_files = sa.table(
        "media_files",
        sa.column("id", _UUID),
        sa.column("kind", sa.String),
        sa.column("ref_id", _UUID),
        sa.column("path", sa.String),
        sa.column("scan_state", sa.String),
        sa.column("missing_since", sa.DateTime(timezone=True)),
    )
    movies = sa.table("movies", sa.column("id", _UUID), sa.column("tmdb_id", sa.Integer))
    tracks = sa.table("tracks", sa.column("id", _UUID), sa.column("mbid", sa.String))
    episodes = sa.table(
        "episodes",
        sa.column("id", _UUID), sa.column("series_id", _UUID),
        sa.column("season_number", sa.Integer), sa.column("episode_number", sa.Integer),
    )
    series = sa.table(
        "series",
        sa.column("id", _UUID), sa.column("tvdb_id", sa.Integer), sa.column("tmdb_id", sa.Integer),
    )

    # 5a. Backfill ref_kind, ref_id, last_path, ref_key on existing watch_history rows.
    rows = list(bind.execute(
        sa.select(
            watch_history.c.id,
            watch_history.c.media_file_id,
        ).where(watch_history.c.media_file_id.is_not(None))
    ))
    for row in rows:
        mf = bind.execute(
            sa.select(media_files.c.id, media_files.c.kind, media_files.c.ref_id, media_files.c.path)
            .where(media_files.c.id == row.media_file_id)
        ).first()
        if mf is None:
            continue
        ref_key = _build_ref_key(bind, mf.kind, mf.ref_id, movies, tracks, episodes, series)
        bind.execute(
            watch_history.update()
            .where(watch_history.c.id == row.id)
            .values(ref_kind=mf.kind, ref_id=mf.id, last_path=mf.path, ref_key=ref_key)
        )

    # 5b. Backfill last_path and ref_key on existing track_plays rows.
    tp_rows = list(bind.execute(
        sa.select(track_plays.c.id, track_plays.c.track_id)
        .where(track_plays.c.track_id.is_not(None))
    ))
    for row in tp_rows:
        mf_row = bind.execute(
            sa.select(media_files.c.path)
            .where(sa.cast(media_files.c.kind, sa.String) == "track")
            .where(media_files.c.ref_id == row.track_id)
        ).first()
        path = mf_row.path if mf_row else None
        trk = bind.execute(
            sa.select(tracks.c.mbid).where(tracks.c.id == row.track_id)
        ).first()
        ref_key = f"mbrec:{trk.mbid}" if trk and trk.mbid else None
        bind.execute(
            track_plays.update()
            .where(track_plays.c.id == row.id)
            .values(last_path=path, ref_key=ref_key)
        )

    # 5c. Set missing_since = now() on files already marked missing.
    now = datetime.now(timezone.utc)
    bind.execute(
        media_files.update()
        .where(sa.cast(media_files.c.scan_state, sa.String) == "missing")
        .where(media_files.c.missing_since.is_(None))
        .values(missing_since=now)
    )


def _build_ref_key(bind, kind: str, ref_id: str, movies, tracks, episodes, series):
    """Build a provider key string for a media_files row during the migration backfill."""
    if kind == "movie":
        row = bind.execute(
            sa.select(movies.c.tmdb_id).where(movies.c.id == ref_id)
        ).first()
        if row and row.tmdb_id:
            return f"tmdb:{row.tmdb_id}"
    elif kind == "episode":
        ep = bind.execute(
            sa.select(episodes.c.series_id, episodes.c.season_number, episodes.c.episode_number)
            .where(episodes.c.id == ref_id)
        ).first()
        if ep:
            ser = bind.execute(
                sa.select(series.c.tvdb_id, series.c.tmdb_id).where(series.c.id == ep.series_id)
            ).first()
            if ser:
                s, e = ep.season_number, ep.episode_number
                if ser.tvdb_id:
                    return f"tvdb:{ser.tvdb_id}:s{s}e{e}"
                if ser.tmdb_id:
                    return f"tmdb:{ser.tmdb_id}:s{s}e{e}"
    elif kind == "track":
        row = bind.execute(
            sa.select(tracks.c.mbid).where(tracks.c.id == ref_id)
        ).first()
        if row and row.mbid:
            return f"mbrec:{row.mbid}"
    return None


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    bind = op.get_bind()

    # Clean up rows that would violate the NOT NULL constraints before restoring them.
    watch_history = sa.table(
        "watch_history",
        sa.column("media_file_id", _UUID),
    )
    track_plays = sa.table(
        "track_plays",
        sa.column("track_id", _UUID),
    )
    bind.execute(watch_history.delete().where(watch_history.c.media_file_id.is_(None)))
    bind.execute(track_plays.delete().where(track_plays.c.track_id.is_(None)))

    # media_files: drop missing_since.
    with op.batch_alter_table("media_files") as batch:
        batch.drop_column("missing_since")

    # track_plays: restore track_id to NOT NULL with CASCADE, drop added columns.
    with op.batch_alter_table("track_plays") as batch:
        batch.drop_column("last_path")
        batch.drop_column("ref_key")
        batch.alter_column(
            "track_id",
            existing_type=sa.String(36),
            nullable=False,
            existing_nullable=True,
        )
        if dialect == "postgresql":
            batch.drop_constraint("fk_track_plays_track", type_="foreignkey")
            batch.create_foreign_key(
                "track_plays_track_id_fkey",
                "tracks",
                ["track_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # watch_history: drop added columns, restore media_file_id to NOT NULL with CASCADE.
    with op.batch_alter_table("watch_history") as batch:
        batch.drop_column("ref_key")
        batch.drop_column("last_path")
        batch.drop_column("ref_id")
        batch.drop_column("ref_kind")
        batch.alter_column(
            "media_file_id",
            existing_type=sa.String(36),
            nullable=False,
            existing_nullable=True,
        )
        if dialect == "postgresql":
            batch.drop_constraint("fk_watch_history_media_file", type_="foreignkey")
            batch.create_foreign_key(
                "watch_history_media_file_id_fkey",
                "media_files",
                ["media_file_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # Drop metadata_locks.
    op.drop_index("ix_metadata_locks_entity", table_name="metadata_locks")
    op.drop_table("metadata_locks")
