"""login_attempts: durable login throttle (SEC-P1-4)

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-06

Replaces the in-process failed-login counter with a durable table so the
throttle survives a restart and would coordinate across workers. One row per
failed or blocked attempt; counted over a sliding window across (account+IP),
(account, all IPs) and (IP, all accounts).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_attempts_username_at", "login_attempts", ["username", "at"],
    )
    op.create_index(
        "ix_login_attempts_ip_at", "login_attempts", ["client_ip", "at"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_ip_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_username_at", table_name="login_attempts")
    op.drop_table("login_attempts")
