"""Version picking: choose the best media file from a list of versions.

Sort order (identical to what the frontend replicates client-side):
  1. is_preferred_version = True first (admin-pinned)
  2. height descending (null last)
  3. bitrate_kbps descending (null last)
  4. codec score descending: HEVC/H.265 = 2, AVC/H.264 = 1, anything else = 0
"""
from __future__ import annotations

from typing import Optional

from app.models.media_file import MediaFile


def _codec_score(codec: Optional[str]) -> int:
    if not codec:
        return 0
    c = codec.lower().replace(".", "").replace("-", "")
    if c in ("hevc", "h265"):
        return 2
    if c in ("avc", "h264"):
        return 1
    return 0


def best_file(files: list[MediaFile]) -> Optional[MediaFile]:
    """Return the best version from a list, or None for an empty list."""
    if not files:
        return None
    return min(
        files,
        key=lambda f: (
            not bool(f.is_preferred_version),
            -(f.height or 0),
            -(f.bitrate_kbps or 0),
            -_codec_score(f.video_codec),
        ),
    )
