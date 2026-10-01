"""add art_overrides table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-18

Single table that drives manual image overrides for artists, movies,
series, and music videos. The read path checks this table first and
falls through to the existing image_path / poster_path / backdrop_path
columns on the entity tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "art_overrides",
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("local_path", sa.String(1024), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(2048)),
        sa.Column(
            "set_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "entity_kind", "entity_id", "role",
            name="pk_art_overrides",
        ),
    )
    # Lookup hot path: resolve_art() filters on (entity_kind, entity_id)
    # and the PK alone can't satisfy that without also specifying role.
    op.create_index(
        "ix_art_overrides_entity",
        "art_overrides",
        ["entity_kind", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_art_overrides_entity", table_name="art_overrides")
    op.drop_table("art_overrides")
