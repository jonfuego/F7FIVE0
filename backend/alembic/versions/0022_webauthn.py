"""webauthn passkeys: credentials + single-use challenges

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-28

arcHIVE 1.3.0 passkey sign-in. Additive: two new tables, no changes to any
existing table, so existing rows and every prior endpoint are untouched.

- `webauthn_credentials`: one row per registered passkey (credential id, COSE
  public key, signature counter, transports, aaguid, name, timestamps).
- `webauthn_challenges`: one row per issued register/login challenge, stored in
  the DB (not memory) so the stateless single-worker API can verify a ceremony
  it started and enforce single use across restarts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", sa.String(length=512), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", sa.String(length=128), nullable=True),
        sa.Column("aaguid", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False, server_default="Passkey"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id", name="uq_webauthn_credentials_credential_id"),
    )
    op.create_index(
        "ix_webauthn_credentials_user", "webauthn_credentials", ["user_id"],
    )

    op.create_table(
        "webauthn_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("challenge", sa.String(length=512), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webauthn_challenges_challenge", "webauthn_challenges", ["challenge"],
    )
    op.create_index(
        "ix_webauthn_challenges_user_id", "webauthn_challenges", ["user_id"],
    )
    op.create_index(
        "ix_webauthn_challenges_lookup", "webauthn_challenges", ["challenge", "kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_webauthn_challenges_lookup", table_name="webauthn_challenges")
    op.drop_index("ix_webauthn_challenges_user_id", table_name="webauthn_challenges")
    op.drop_index("ix_webauthn_challenges_challenge", table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index("ix_webauthn_credentials_user", table_name="webauthn_credentials")
    op.drop_table("webauthn_credentials")
