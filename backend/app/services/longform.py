"""Shared rules for long-form audio: skip, played, chapters, speed.

Podcasts use these today. They carry no podcast-only names on purpose, so
audiobooks can reuse them as they are. The same numbers live in
`frontend/lib/longform.ts` and `mobile/src/player/longform.ts`; keep the three
in step.

- Skip: back 15 s, forward 30 s.
- Played: within 30 s of the end, or past 95 percent, whichever comes first.
  A length that is not known never counts as played.
- Chapters: `{start_sec, title, img?, url?}`, sorted by start.
- Speed: 0.5 to 3.0, a per-user view pref (`podcast_speed`).
"""
from __future__ import annotations

from typing import Optional, Sequence

SKIP_BACK_SEC = 15
SKIP_FORWARD_SEC = 30
PLAYED_TAIL_SEC = 30
PLAYED_FRACTION = 0.95
MIN_SPEED = 0.5
MAX_SPEED = 3.0
DEFAULT_SPEED = 1.0


def skip_back(position_sec: float, duration_sec: Optional[float] = None) -> float:
    """Where a skip back lands: 15 s earlier, never before the start."""
    return max(0, position_sec - SKIP_BACK_SEC)


def skip_forward(position_sec: float, duration_sec: Optional[float] = None) -> float:
    """Where a skip forward lands: 30 s later, never past the end when the
    length is known."""
    target = position_sec + SKIP_FORWARD_SEC
    if duration_sec and duration_sec > 0:
        return min(duration_sec, target)
    return target


def played_threshold(duration_sec: Optional[float]) -> Optional[float]:
    """The position from which an episode counts as played, or None when its
    length is unknown."""
    if not duration_sec or duration_sec <= 0:
        return None
    return min(duration_sec - PLAYED_TAIL_SEC, duration_sec * PLAYED_FRACTION)


def is_played(position_sec: Optional[float], duration_sec: Optional[float]) -> bool:
    threshold = played_threshold(duration_sec)
    if threshold is None or position_sec is None:
        return False
    return position_sec >= threshold


def chapter_at(chapters: Sequence[dict], position_sec: float) -> Optional[int]:
    """Index of the chapter playing at `position_sec`, or None when there are
    no chapters or the position is before the first one."""
    found: Optional[int] = None
    for i, chapter in enumerate(chapters):
        if chapter.get("start_sec", 0) <= max(0, position_sec):
            found = i
        else:
            break
    return found


def state_for(*, position_sec: Optional[float], played: bool) -> dict:
    """What a caller sees for one episode: `new`, `in_progress` with a position,
    or `played`."""
    if played:
        return {"kind": "played"}
    if position_sec and position_sec > 0:
        return {"kind": "in_progress", "position_sec": int(position_sec)}
    return {"kind": "new"}


def clamp_speed(value: object) -> float:
    try:
        speed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    if speed != speed:  # NaN
        return DEFAULT_SPEED
    return min(MAX_SPEED, max(MIN_SPEED, speed))
