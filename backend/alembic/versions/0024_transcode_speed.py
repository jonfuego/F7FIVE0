"""transcode_sessions: record the live ffmpeg encode speed

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-04

Additive: two columns on transcode_sessions so the admin Active streams view
can show the realtime factor and flag a server that has stayed below 1.0x.
The stream gateway parses ffmpeg's -progress output and writes them; the API
(a separate process) reads them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transcode_sessions",
        sa.Column("speed", sa.Float(), nullable=True),
    )
    op.add_column(
        "transcode_sessions",
        sa.Column(
            "below_realtime_sec", sa.Integer(),
            server_default="0", nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("transcode_sessions", "below_realtime_sec")
    op.drop_column("transcode_sessions", "speed")
