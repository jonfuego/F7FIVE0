"""artist merge: aliases, merge records, and credited text

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-10

Adds the storage behind merging one artist into another (punch-list item 2):

  - artist_aliases: a merged-away source name and / or MusicBrainz id pointing
    at the artist it was merged into. The folder scan and the Lidarr sync
    resolve an incoming artist through this table, so a rescan or a sync does
    not recreate the source (for example "2Pac Featuring KC And Jojo" folding
    back into "2Pac").
  - artist_merges: a record of each merge, enough to undo it (the source
    artist's columns as a snapshot and the album ids that moved).
  - albums.credited_as / tracks.credited_as: the artist text as it was
    credited on the record, so a merge does not lose who is on each release.

All additive. Existing installs keep every row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("albums", sa.Column("credited_as", sa.String(length=512), nullable=True))
    op.add_column("tracks", sa.Column("credited_as", sa.String(length=512), nullable=True))

    op.create_table(
        "artist_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("target_artist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name_key", sa.String(length=512), nullable=False),
        sa.Column("source_name", sa.String(length=512), nullable=False),
        sa.Column("source_mbid", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["target_artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_key", name="uq_artist_aliases_name_key"),
    )
    op.create_index("ix_artist_aliases_target_artist_id", "artist_aliases", ["target_artist_id"])
    op.create_index(
        "ux_artist_aliases_source_mbid", "artist_aliases", ["source_mbid"],
        unique=True, postgresql_where=sa.text("source_mbid IS NOT NULL"),
    )

    op.create_table(
        "artist_merges",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("target_artist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=512), nullable=False),
        sa.Column("source_mbid", sa.String(length=64), nullable=True),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("moved_album_ids", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["target_artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artist_merges_target_artist_id", "artist_merges", ["target_artist_id"])


def downgrade() -> None:
    op.drop_index("ix_artist_merges_target_artist_id", table_name="artist_merges")
    op.drop_table("artist_merges")
    op.drop_index("ux_artist_aliases_source_mbid", table_name="artist_aliases")
    op.drop_index("ix_artist_aliases_target_artist_id", table_name="artist_aliases")
    op.drop_table("artist_aliases")
    op.drop_column("tracks", "credited_as")
    op.drop_column("albums", "credited_as")
