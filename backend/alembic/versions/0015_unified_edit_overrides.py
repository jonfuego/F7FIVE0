"""unified edit overrides + Fix Match plumbing

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-03

Adds the schema scaffolding for the unified Edit Overrides modal.

JSONB `overrides` column on the six entity tables that the modal can target:
movies, series, artists, albums, tracks, music_video_releases. Stores
display_name / tagline / year / runtime_min / rating overrides that the
serializers overlay on top of canonical *arr-synced metadata. Sort title
stays in its own column because `_sort_expr` operates at the SQL level
and needs a real column to COALESCE against; everything else can live in
JSONB because it is read at the response-serializer boundary.

`sort_title` lands on `albums` and `tracks` this round so future detail
pages for those entities can extend the same pattern. Movies, series,
artists, and music_video_releases already have their sort columns from
0012 and 0013.

`mbid` lands on `music_video_releases` so Fix Match for releases has
somewhere to write the MusicBrainz release-group id it picks. Mirrors
the `mbid` shape on `artists` and `albums`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OVERRIDES_TABLES = (
    "movies",
    "series",
    "artists",
    "albums",
    "tracks",
    "music_video_releases",
)


def upgrade() -> None:
    for table in _OVERRIDES_TABLES:
        op.add_column(
            table,
            sa.Column(
                "overrides",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

    op.add_column(
        "albums",
        sa.Column("sort_title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tracks",
        sa.Column("sort_title", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "music_video_releases",
        sa.Column("mbid", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ux_music_video_releases_mbid",
        "music_video_releases",
        ["mbid"],
        unique=True,
        postgresql_where=sa.text("mbid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_music_video_releases_mbid",
        table_name="music_video_releases",
    )
    op.drop_column("music_video_releases", "mbid")

    op.drop_column("tracks", "sort_title")
    op.drop_column("albums", "sort_title")

    for table in reversed(_OVERRIDES_TABLES):
        op.drop_column(table, "overrides")
