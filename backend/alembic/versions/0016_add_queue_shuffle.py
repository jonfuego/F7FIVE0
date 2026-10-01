"""add shuffle to playback_queues

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-25

Adds a boolean `shuffle` column on `playback_queues` so the per-user
queue carries shuffle state alongside `repeat_mode`. Existing rows get
`false` via `server_default`; no data backfill needed.

`repeat_mode` is still a free-form `String(8)` at the schema level; the
"one" value is enforced at the Pydantic boundary in `app.api.queue`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playback_queues",
        sa.Column(
            "shuffle",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("playback_queues", "shuffle")
