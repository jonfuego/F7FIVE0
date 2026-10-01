"""add music metadata fields

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-30

Hydrates `artists` and `albums` with MusicBrainz-sourced metadata
(origin country, type, formed/disbanded years, link relationships,
ratings, label) plus a Wikipedia-sourced bio for artists. Lidarr-side
fields (album type, label, disambiguation) get backfilled in the same
sweep without a new external call. Sync time + status mirror the
movie-side migration.

JSONB only; no normalized tables for v1. GIN indexes deferred until a
query path develops.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- artists ----------------------------------------------------------
    op.add_column("artists", sa.Column("country", sa.String(length=8), nullable=True))
    op.add_column(
        "artists", sa.Column("artist_type", sa.String(length=32), nullable=True),
    )
    op.add_column("artists", sa.Column("formed_year", sa.Integer(), nullable=True))
    op.add_column("artists", sa.Column("disbanded_year", sa.Integer(), nullable=True))
    op.add_column(
        "artists",
        sa.Column(
            "links",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("artists", sa.Column("bio_text", sa.Text(), nullable=True))
    op.add_column(
        "artists", sa.Column("bio_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "artists",
        sa.Column("metadata_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artists", sa.Column("metadata_status", sa.String(length=32), nullable=True),
    )

    # ---- albums -----------------------------------------------------------
    op.add_column(
        "albums", sa.Column("album_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "albums",
        sa.Column(
            "secondary_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("albums", sa.Column("label", sa.String(length=256), nullable=True))
    op.add_column("albums", sa.Column("disambiguation", sa.Text(), nullable=True))
    op.add_column("albums", sa.Column("mb_rating", sa.Float(), nullable=True))
    op.add_column(
        "albums",
        sa.Column(
            "links",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "albums",
        sa.Column("metadata_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "albums", sa.Column("metadata_status", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    # ---- albums -----------------------------------------------------------
    op.drop_column("albums", "metadata_status")
    op.drop_column("albums", "metadata_synced_at")
    op.drop_column("albums", "links")
    op.drop_column("albums", "mb_rating")
    op.drop_column("albums", "disambiguation")
    op.drop_column("albums", "label")
    op.drop_column("albums", "secondary_types")
    op.drop_column("albums", "album_type")

    # ---- artists ----------------------------------------------------------
    op.drop_column("artists", "metadata_status")
    op.drop_column("artists", "metadata_synced_at")
    op.drop_column("artists", "bio_source")
    op.drop_column("artists", "bio_text")
    op.drop_column("artists", "links")
    op.drop_column("artists", "disbanded_year")
    op.drop_column("artists", "formed_year")
    op.drop_column("artists", "artist_type")
    op.drop_column("artists", "country")
