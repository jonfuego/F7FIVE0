"""podcast progress: when the device took the saved position

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-15

Adds podcast_episode_progress.client_recorded_at: the device's own time for the
position it saved. A save taken before the stored one (an offline buffer
replay, a late retry) is ignored, so the place never moves back on its own.

Additive and nullable. Existing rows keep their position; their first new save
fills the column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "podcast_episode_progress",
        sa.Column("client_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("podcast_episode_progress", "client_recorded_at")
