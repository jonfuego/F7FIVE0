"""organizer_journals and organizer_journal_items tables

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-19

Adds:
  - organizer_journals table (per-library rename/retag run journal)
  - organizer_journal_items table (one row per file action in a run)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. organizer_journals
    op.create_table(
        "organizer_journals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("library_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "state",
            sa.String(32),
            server_default=sa.text("'preview'"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "item_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("undo_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["libraries.id"],
            ondelete="SET NULL",
            name="fk_organizer_journals_library",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_organizer_journals_created_by",
        ),
    )
    op.create_index("ix_organizer_journals_library", "organizer_journals", ["library_id"])
    op.create_index("ix_organizer_journals_started_at", "organizer_journals", ["started_at"])

    # 2. organizer_journal_items
    op.create_table(
        "organizer_journal_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_kind", sa.String(32), nullable=False),
        sa.Column("old_path", sa.Text(), nullable=False),
        sa.Column("new_path", sa.Text(), nullable=True),
        sa.Column("old_tags", sa.Text(), nullable=True),
        sa.Column("new_tags", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["organizer_journals.id"],
            ondelete="CASCADE",
            name="fk_organizer_journal_items_journal",
        ),
        sa.ForeignKeyConstraint(
            ["media_file_id"],
            ["media_files.id"],
            ondelete="SET NULL",
            name="fk_organizer_journal_items_media_file",
        ),
    )
    op.create_index("ix_organizer_journal_items_journal", "organizer_journal_items", ["journal_id"])
    op.create_index("ix_organizer_journal_items_media_file", "organizer_journal_items", ["media_file_id"])


def downgrade() -> None:
    op.drop_index("ix_organizer_journal_items_media_file", table_name="organizer_journal_items")
    op.drop_index("ix_organizer_journal_items_journal", table_name="organizer_journal_items")
    op.drop_table("organizer_journal_items")

    op.drop_index("ix_organizer_journals_started_at", table_name="organizer_journals")
    op.drop_index("ix_organizer_journals_library", table_name="organizer_journals")
    op.drop_table("organizer_journals")
