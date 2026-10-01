r"""rename users.email to users.username

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-18

Dropping email-as-identity in favor of a plain username. The column is
renamed in place (so existing rows survive and the unique constraint
stays enforced throughout). The unique index is dropped and re-created
under its new name so `\d users` in psql doesn't still read as "ix_users_email".

Data migration note: existing rows keep their current value as their
username. Any row that should get a shorter username is updated by hand
outside this file, because Alembic should not carry instance-specific
data patches.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.alter_column("users", "email", new_column_name="username")
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.alter_column("users", "username", new_column_name="email")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
