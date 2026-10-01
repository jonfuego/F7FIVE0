"""extend sort overrides for music_video_release / music_video

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-03

The existing sort-override scheme stores a per-row column on each entity
table (movies.sort_title, series.sort_title, artists.sort_name) rather than
a separate sort_overrides table with a CHECK constraint over `entity_kind`.
There is therefore no DDL to relax: the new entity kinds `music_video_release`
and `music_video` are already free to be admitted by the admin endpoint
without touching the database. Migration 0013 already added
`music_video_releases.sort_title`, `music_video_releases.sort_year`, and
`music_videos.sort_title` columns alongside the new entities.

This migration is intentionally a no-op so the head bumps to 0014 and the
chain documents that the new admin allowed-kinds (see admin.py) became
valid at this revision.
"""
from typing import Sequence, Union


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No DDL change. Sort overrides for music_video_release and music_video
    # are stored as columns added in migration 0013. See module docstring.
    pass


def downgrade() -> None:
    # Symmetric no-op.
    pass
