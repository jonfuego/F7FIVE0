"""collections, collection_items, tmdb_collection fields, is_preferred_version

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-18

Adds:
  - collections table (TMDB-auto and admin-manual movie/media collections)
  - collection_items table (polymorphic membership)
  - movies.tmdb_collection_id, tmdb_collection_name, tmdb_collection_checked_at
  - media_files.is_preferred_version (admin-pinned best version flag)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. collections table
    op.create_table(
        "collections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=True),
        sa.Column("tmdb_collection_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_auto",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_collection_id", name="uq_collections_tmdb_id"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_collections_created_by",
        ),
    )
    op.create_index("ix_collections_tmdb_id", "collections", ["tmdb_collection_id"])

    # 2. collection_items table
    op.create_table(
        "collection_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id", "entity_kind", "entity_id",
            name="uq_collection_items_coll_kind_entity",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            ondelete="CASCADE",
            name="fk_collection_items_collection",
        ),
    )
    op.create_index("ix_collection_items_collection", "collection_items", ["collection_id"])
    op.create_index(
        "ix_collection_items_entity",
        "collection_items",
        ["entity_kind", "entity_id"],
    )

    # 3. movies: add tmdb_collection_id, tmdb_collection_name, tmdb_collection_checked_at
    with op.batch_alter_table("movies") as batch:
        batch.add_column(sa.Column("tmdb_collection_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("tmdb_collection_name", sa.String(255), nullable=True))
        batch.add_column(
            sa.Column("tmdb_collection_checked_at", sa.DateTime(timezone=True), nullable=True)
        )

    # 4. media_files: add is_preferred_version
    with op.batch_alter_table("media_files") as batch:
        batch.add_column(sa.Column("is_preferred_version", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Reverse order: files, movies, items, collections
    with op.batch_alter_table("media_files") as batch:
        batch.drop_column("is_preferred_version")

    with op.batch_alter_table("movies") as batch:
        batch.drop_column("tmdb_collection_checked_at")
        batch.drop_column("tmdb_collection_name")
        batch.drop_column("tmdb_collection_id")

    op.drop_index("ix_collection_items_entity", table_name="collection_items")
    op.drop_index("ix_collection_items_collection", table_name="collection_items")
    op.drop_table("collection_items")

    op.drop_index("ix_collections_tmdb_id", table_name="collections")
    op.drop_table("collections")
