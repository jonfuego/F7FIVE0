"""seed the synthetic system user for sync-originated art overrides

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-26

Adds a `system` value to the `user_role` enum and seeds a fixed-UUID
user row (00000000-0000-0000-0000-000000000001) that owns art_overrides
rows written by *arr sync.

`art_overrides.set_by` is a NOT NULL FK to users.id. Sync does not act
as a real user, so without this row we would either have to make
set_by nullable (losing audit trail semantics) or skip writing rows from
sync. Seeding a non-loginable user is the cleanest path: is_active is
false and password_hash is "!" (an unverifiable bcrypt sentinel), so
nobody can authenticate as it.

See decision: 2026-05-26_local-first-art-on-sync.

The intended filename in the original task spec was 0005_local_first_art
but migrations 0005 through 0016 already exist; this file is the next
sequential revision and carries the same content.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in
    # Postgres, so escape Alembic's per-revision transaction for this op.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'system'")

    # Seed the synthetic user. ON CONFLICT keeps this idempotent so
    # re-running the migration after a partial failure is safe.
    op.execute(
        f"""
        INSERT INTO users (
            id, username, password_hash, display_name, role, is_active,
            created_at, updated_at
        ) VALUES (
            '{SYSTEM_USER_ID}',
            '__system__',
            '!',
            'F7FIVE0 System',
            'system',
            false,
            now(),
            now()
        )
        ON CONFLICT (id) DO UPDATE SET
            role = EXCLUDED.role,
            is_active = EXCLUDED.is_active
        """
    )


def downgrade() -> None:
    # Drop the seeded row. art_overrides rows with set_by pointing at the
    # system user must be cleared first or the FK will block; that is the
    # operator's responsibility (downgrade implies rollback to the
    # remote-URL world, which has no use for sync-owned overrides).
    op.execute(
        f"DELETE FROM users WHERE id = '{SYSTEM_USER_ID}'"
    )
    # Postgres has no native "remove enum value" path; leave 'system' in
    # the user_role type. Cosmetic only; nothing else references it.
