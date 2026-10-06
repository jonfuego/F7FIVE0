"""user_view_prefs: saved library views per user

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-05

Additive: one row per (user, view key) holding a small JSON value, so a
library view (Music browse tab, movie genre and sort, TV filter, ...) follows
the user across web, phone and TV. Deleting a user deletes their rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_view_prefs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("view_key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "view_key"),
    )


def downgrade() -> None:
    op.drop_table("user_view_prefs")
