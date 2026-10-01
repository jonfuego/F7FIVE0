"""add music genres jsonb columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-30

Adds `artists.genres` and `albums.genres` JSONB columns with NOT NULL
default '[]'::jsonb plus a GIN index on each. Lidarr already returns
`genres` on its artist and album payloads; the sync service copies the
field on upsert and the `backfill-genres` CLI command walks every row
once after the migration so the by-genre playlist endpoint has data to
read.

Per the audio-playlists spec, only album-level genres are used for
filtering. Artist-level genres feed the artist-radio neighbor matcher.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "artists",
        sa.Column(
            "genres",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "albums",
        sa.Column(
            "genres",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_artists_genres",
        "artists",
        ["genres"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_albums_genres",
        "albums",
        ["genres"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_albums_genres", table_name="albums")
    op.drop_index("ix_artists_genres", table_name="artists")
    op.drop_column("albums", "genres")
    op.drop_column("artists", "genres")
