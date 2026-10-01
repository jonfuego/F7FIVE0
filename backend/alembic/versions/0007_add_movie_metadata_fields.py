"""add movie metadata fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-30

Hydrates `movies` with TMDB-sourced metadata that Radarr's `overview`
field doesn't carry: cast, directors, tagline, ratings. Sync time and
status columns let the metadata-enrichment runner skip rows whose data
is fresh and surface failure modes (no_external_id, failed) without
adding a separate table.

JSONB on the row is intentional. v1 has no "all movies starring X"
query path; the cast / directors columns exist so the detail page can
render a small thumbnail row in one fetch. GIN indexes are deferred
until a query path develops.

Python attribute is `movie_cast` to dodge the SQL keyword + builtin
collision; the column name in the database is `cast`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("movies", sa.Column("tagline", sa.Text(), nullable=True))
    op.add_column(
        "movies",
        sa.Column(
            "cast",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "movies",
        sa.Column(
            "directors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("movies", sa.Column("tmdb_rating", sa.Float(), nullable=True))
    op.add_column("movies", sa.Column("tmdb_vote_count", sa.Integer(), nullable=True))
    op.add_column(
        "movies",
        sa.Column("metadata_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "movies",
        sa.Column("metadata_status", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("movies", "metadata_status")
    op.drop_column("movies", "metadata_synced_at")
    op.drop_column("movies", "tmdb_vote_count")
    op.drop_column("movies", "tmdb_rating")
    op.drop_column("movies", "directors")
    op.drop_column("movies", "cast")
    op.drop_column("movies", "tagline")
