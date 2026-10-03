r"""add music_video_releases + restructure music_videos

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-03

Interpose `music_video_releases` between `artists` and `music_videos` so the
model becomes Artist → Release → Video. The folder contract on disk is
`<root>\<Artist>\<Release>\[Disc NN\]<Title>.<ext>`.

Adds `release_id`, `disc_number`, `track_number` to `music_videos`. Backfills
`release_id` by splitting the existing POSIX `source_subpath` on `/` and
treating the first segment as the release name. If the second segment matches
the disc-folder regex it strips out and seeds `disc_number`. Then the column
is flipped to NOT NULL.

Also drops the legacy partial unique index `ux_music_videos_artist_subpath`
in favor of `ux_music_videos_release_subpath` over `(release_id, source_subpath)`.

Downgrade is destructive in the strict sense (drops the new table) but the old
`(artist_id, source_subpath)` mapping is reconstructable: copy the release
title back as the first segment of `music_videos.source_subpath`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New parent table.
    op.create_table(
        "music_video_releases",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "artist_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("cover_path", sa.String(length=1024), nullable=True),
        sa.Column("source_subpath", sa.String(length=1024), nullable=False),
        # Per-row sort overrides; mirror the movies/series/artists pattern.
        sa.Column("sort_title", sa.String(length=255), nullable=True),
        sa.Column("sort_year", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_music_video_releases_artist_subpath",
        "music_video_releases",
        ["artist_id", "source_subpath"],
        unique=True,
    )
    op.create_index(
        "ix_music_video_releases_artist_year",
        "music_video_releases",
        ["artist_id", sa.text("release_year DESC NULLS LAST"), "title"],
    )

    # New columns on music_videos.
    op.add_column(
        "music_videos",
        sa.Column(
            "release_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("music_video_releases.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "music_videos",
        sa.Column(
            "disc_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "music_videos",
        sa.Column("track_number", sa.Integer(), nullable=True),
    )
    # Per-video sort override.
    op.add_column(
        "music_videos",
        sa.Column("sort_title", sa.String(length=255), nullable=True),
    )

    # Backfill: for every music_videos row with non-null source_subpath,
    # take the first POSIX segment as the release name. If the second
    # segment matches the disc-folder regex, strip it and seed disc_number.
    # Year parsing picks the last 19xx/20xx token in the title.
    #
    # The CTE shape: split_parts CTE produces (mv_id, artist_id, segs[]) per
    # row; releases CTE upserts one row per (artist_id, first_segment); then
    # we update music_videos with the release_id and rewritten subpath.
    op.execute(
        r"""
        WITH split AS (
            SELECT
                mv.id          AS mv_id,
                mv.artist_id   AS artist_id,
                mv.source_subpath AS subpath,
                regexp_split_to_array(mv.source_subpath, '/') AS segs
            FROM music_videos mv
            WHERE mv.source_subpath IS NOT NULL
              AND char_length(mv.source_subpath) > 0
        ),
        norm AS (
            SELECT
                mv_id,
                artist_id,
                subpath,
                segs[1] AS release_name,
                CASE
                    WHEN array_length(segs, 1) >= 2
                         AND segs[2] ~* '^(disc|cd|dvd|bd)[\s_-]*0*([0-9]+)$'
                    THEN COALESCE(
                        NULLIF(
                            regexp_replace(
                                segs[2],
                                '^(disc|cd|dvd|bd)[\s_-]*0*([0-9]+)$',
                                '\2',
                                'i'
                            ),
                            ''
                        )::int,
                        1
                    )
                    ELSE 1
                END AS parsed_disc,
                CASE
                    WHEN array_length(segs, 1) >= 2
                         AND segs[2] ~* '^(disc|cd|dvd|bd)[\s_-]*0*([0-9]+)$'
                    THEN array_to_string(segs[3:], '/')
                    ELSE array_to_string(segs[2:], '/')
                END AS rel_subpath
            FROM split
        ),
        ins AS (
            INSERT INTO music_video_releases
                (artist_id, title, source_subpath, release_year)
            SELECT DISTINCT
                n.artist_id,
                n.release_name,
                n.release_name,
                NULLIF(
                    (regexp_match(n.release_name, '(?:^|\s)(19[0-9]{2}|20[0-9]{2})(?:\s|$)'))[1],
                    ''
                )::int
            FROM norm n
            ON CONFLICT (artist_id, source_subpath) DO NOTHING
            RETURNING id, artist_id, source_subpath
        ),
        all_releases AS (
            SELECT id, artist_id, source_subpath FROM ins
            UNION
            SELECT r.id, r.artist_id, r.source_subpath
            FROM music_video_releases r
            JOIN norm n
              ON n.artist_id = r.artist_id
             AND n.release_name = r.source_subpath
        )
        UPDATE music_videos mv
        SET
            release_id = ar.id,
            disc_number = n.parsed_disc,
            source_subpath = NULLIF(n.rel_subpath, '')
        FROM norm n
        JOIN all_releases ar
          ON ar.artist_id = n.artist_id
         AND ar.source_subpath = n.release_name
        WHERE mv.id = n.mv_id
        """
    )

    # Replace the legacy unique index with the release-scoped one.
    op.drop_index("ux_music_videos_artist_subpath", table_name="music_videos")
    op.create_index(
        "ux_music_videos_release_subpath",
        "music_videos",
        ["release_id", "source_subpath"],
        unique=True,
        postgresql_where=sa.text("source_subpath IS NOT NULL"),
    )

    # Replace the (artist_id, year) index with one keyed on release+disc+track
    # for in-release ordering. The artist_id column stays in place so existing
    # queries don't break atomically; a follow-up migration will drop it.
    op.drop_index("ix_music_videos_artist_year", table_name="music_videos")
    op.create_index(
        "ix_music_videos_release_disc_track",
        "music_videos",
        ["release_id", "disc_number", "track_number"],
    )

    # Any music_videos row with a NULL source_subpath had no backfill input;
    # park those under a placeholder release per artist so we can flip
    # release_id to NOT NULL without losing the rows. The next scan re-keys
    # them properly once it walks the disk again.
    op.execute(
        r"""
        WITH orphans AS (
            SELECT DISTINCT artist_id
            FROM music_videos
            WHERE release_id IS NULL
        ),
        ins AS (
            INSERT INTO music_video_releases (artist_id, title, source_subpath)
            SELECT artist_id, '__unscanned__', '__unscanned__'
            FROM orphans
            ON CONFLICT (artist_id, source_subpath) DO NOTHING
            RETURNING id, artist_id
        ),
        all_orphans AS (
            SELECT id, artist_id FROM ins
            UNION
            SELECT r.id, r.artist_id
            FROM music_video_releases r
            WHERE r.source_subpath = '__unscanned__'
              AND r.artist_id IN (SELECT artist_id FROM orphans)
        )
        UPDATE music_videos mv
        SET release_id = ao.id
        FROM all_orphans ao
        WHERE mv.release_id IS NULL
          AND mv.artist_id = ao.artist_id
        """
    )

    # Now safe to flip NOT NULL.
    op.alter_column("music_videos", "release_id", nullable=False)


def downgrade() -> None:
    # Reconstruct the artist_id-scoped subpath: prepend the release title.
    op.execute(
        r"""
        UPDATE music_videos mv
        SET source_subpath = CASE
            WHEN mv.source_subpath IS NULL OR mv.source_subpath = ''
                THEN r.source_subpath
            ELSE r.source_subpath || '/' || mv.source_subpath
        END
        FROM music_video_releases r
        WHERE mv.release_id = r.id
        """
    )

    op.drop_index("ix_music_videos_release_disc_track", table_name="music_videos")
    op.create_index(
        "ix_music_videos_artist_year",
        "music_videos",
        ["artist_id", "year"],
    )

    op.drop_index("ux_music_videos_release_subpath", table_name="music_videos")
    op.create_index(
        "ux_music_videos_artist_subpath",
        "music_videos",
        ["artist_id", "source_subpath"],
        unique=True,
        postgresql_where=sa.text("source_subpath IS NOT NULL"),
    )

    op.drop_column("music_videos", "sort_title")
    op.drop_column("music_videos", "track_number")
    op.drop_column("music_videos", "disc_number")
    op.drop_column("music_videos", "release_id")

    op.drop_index(
        "ix_music_video_releases_artist_year",
        table_name="music_video_releases",
    )
    op.drop_index(
        "ux_music_video_releases_artist_subpath",
        table_name="music_video_releases",
    )
    op.drop_table("music_video_releases")
