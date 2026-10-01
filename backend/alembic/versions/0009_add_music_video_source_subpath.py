"""add music video source_subpath

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-02

Tighten the music-video dedup key. Adds `source_subpath` (POSIX-style
relative path from the artist folder) to `music_videos` and a partial
unique index over (artist_id, source_subpath) so the same title can
appear in multiple album subfolders without colliding.

Backfill is best-effort: rows with exactly one MediaFile (kind=
music_video) get `os.path.basename(media_file.path)` written to
source_subpath. Rows with zero or multiple files are left NULL; the next
scan re-keys them once disk paths are walked recursively.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "music_videos",
        sa.Column("source_subpath", sa.String(length=1024), nullable=True),
    )

    # Backfill with the basename of the single associated MediaFile when
    # the mapping is unambiguous. Cross-platform path separator handling
    # is not needed here: we strip everything up to the last '\' or '/'
    # and store what's left.
    op.execute(
        """
        UPDATE music_videos AS mv
        SET source_subpath = sub.basename
        FROM (
            SELECT
                f.ref_id AS mv_id,
                regexp_replace(f.path, '^.*[\\\\/]', '') AS basename
            FROM media_files f
            WHERE f.kind = 'music_video'
              AND f.ref_id IN (
                  SELECT ref_id
                  FROM media_files
                  WHERE kind = 'music_video'
                  GROUP BY ref_id
                  HAVING COUNT(*) = 1
              )
        ) AS sub
        WHERE mv.id = sub.mv_id
        """
    )

    op.create_index(
        "ux_music_videos_artist_subpath",
        "music_videos",
        ["artist_id", "source_subpath"],
        unique=True,
        postgresql_where=sa.text("source_subpath IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_music_videos_artist_subpath", table_name="music_videos")
    op.drop_column("music_videos", "source_subpath")
