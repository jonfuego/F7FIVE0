"""add sort_title / sort_name overrides

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-02

Per-row sort overrides for movies, series, and artists. Nullable; when
null the list endpoints fall back to an article-stripped lowercase
key on the canonical title/name (see `_sort_key` in `app/api/library.py`).

Lets the franchise titles that don't sort alphabetically (Star Wars,
LOTR, Bond, etc.) be set explicitly without polluting the public title.
The 99% of rows leave the column null and the algorithmic fallback
handles them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column("sort_title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "series",
        sa.Column("sort_title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "artists",
        sa.Column("sort_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("artists", "sort_name")
    op.drop_column("series", "sort_title")
    op.drop_column("movies", "sort_title")
