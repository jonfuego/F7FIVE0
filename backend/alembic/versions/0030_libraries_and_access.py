"""libraries as named groups of folders, library_id on files, per-user access

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-17

Turns `libraries` from one-row-per-folder into named libraries (one or more per
kind), with their folders in a new `library_folders` table. Stamps every media
file with the library it came from (`media_files.library_id`) and adds a
per-user deny-list (`user_library_access`) so an admin can hide a library from a
user.

Non-destructive: `libraries.root_path` is kept (made nullable) and every
existing per-folder row's path is moved into a `library_folders` row under one
canonical named library per kind. `media_files.library_id` starts null (treated
as visible to all) and a one-time backfill job fills it.

Downgrade drops the two new tables, the new `media_files.library_id` column and
the added `libraries` columns. It leaves `root_path` nullable (the per-folder
rows cannot be faithfully rebuilt) and leaves media files without a library id.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Canonical display name per kind for the one library each kind collapses to.
_CANONICAL_NAME = {
    "movies": "Movies",
    "tv": "TV",
    "music": "Music",
    "music_videos": "Music Videos",
    "podcasts": "Podcasts",
}


def upgrade() -> None:
    # 1. New columns on libraries, and make root_path nullable.
    with op.batch_alter_table("libraries") as batch:
        batch.add_column(sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("settings", sa.Text(), nullable=True))
        batch.alter_column("root_path", existing_type=sa.String(length=1024), nullable=True)

    # 2. library_folders: the authoritative folder source going forward.
    op.create_table(
        "library_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("library_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_library_folders_path"),
    )
    op.create_index("ix_library_folders_library", "library_folders", ["library_id"])

    # 3. user_library_access: a row hides the library from that user (deny-list).
    op.create_table(
        "user_library_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("library_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "library_id", name="uq_user_library_access"),
    )
    op.create_index("ix_user_library_access_user", "user_library_access", ["user_id"])

    # 4. media_files.library_id (nullable FK, indexed).
    with op.batch_alter_table("media_files") as batch:
        batch.add_column(sa.Column("library_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch.create_foreign_key(
            "fk_media_files_library", "libraries", ["library_id"], ["id"], ondelete="SET NULL",
        )
    op.create_index("ix_media_files_library", "media_files", ["library_id"])

    # 5. Data step: collapse per-folder library rows into one named library per
    #    kind, moving each old root_path into a library_folders row.
    _migrate_folders_into_libraries()


def _migrate_folders_into_libraries() -> None:
    bind = op.get_bind()
    # Lightweight table defs for the data step. ids use sa.String so the WHERE
    # and INSERT binds are representation-agnostic (PostgreSQL casts the string
    # to its native uuid; SQLite stores it verbatim), rather than depending on a
    # dialect-specific uuid serialization.
    libraries = sa.table(
        "libraries",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("kind", sa.String),
        sa.column("root_path", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    folders = sa.table(
        "library_folders",
        sa.column("id", sa.String),
        sa.column("library_id", sa.String),
        sa.column("path", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    rows = list(bind.execute(
        sa.select(
            libraries.c.id, libraries.c.kind, libraries.c.root_path, libraries.c.created_at,
        ).order_by(libraries.c.kind, libraries.c.created_at)
    ))
    by_kind: dict[str, list] = {}
    for r in rows:
        by_kind.setdefault(str(r.kind), []).append(r)

    for kind, kind_rows in by_kind.items():
        canonical = kind_rows[0]
        # Move every row's folder into library_folders under the canonical row.
        for r in kind_rows:
            if r.root_path:
                bind.execute(folders.insert().values(
                    id=str(uuid.uuid4()), library_id=canonical.id, path=r.root_path,
                    created_at=r.created_at,
                ))
        # Delete the extra (non-canonical) library rows.
        extra_ids = [r.id for r in kind_rows[1:]]
        if extra_ids:
            bind.execute(libraries.delete().where(libraries.c.id.in_(extra_ids)))
        # Rename the canonical row and clear its legacy root_path.
        bind.execute(
            libraries.update()
            .where(libraries.c.id == canonical.id)
            .values(name=_CANONICAL_NAME.get(kind, canonical.kind), root_path=None, sort_order=0)
        )


def downgrade() -> None:
    op.drop_index("ix_media_files_library", table_name="media_files")
    with op.batch_alter_table("media_files") as batch:
        batch.drop_constraint("fk_media_files_library", type_="foreignkey")
        batch.drop_column("library_id")

    op.drop_index("ix_user_library_access_user", table_name="user_library_access")
    op.drop_table("user_library_access")
    op.drop_index("ix_library_folders_library", table_name="library_folders")
    op.drop_table("library_folders")

    with op.batch_alter_table("libraries") as batch:
        batch.drop_column("settings")
        batch.drop_column("sort_order")
