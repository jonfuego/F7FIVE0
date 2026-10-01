"""On Deck selection (Plex semantics), spec section H / criterion 38.

"On Deck" is the next episode to watch for every series the viewer has
started: resume the earliest in-progress episode if there is one, otherwise
the first unwatched episode after the last completed one. A series whose
episodes are all completed drops off. Pure (no DB) so it unit-tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class EpisodeRef:
    episode_id: object
    season_number: int
    episode_number: int
    media_file_id: Optional[object]


@dataclass(frozen=True)
class ProgressRef:
    position_sec: int
    completed: bool


def next_episode(
    episodes: Sequence[EpisodeRef],
    progress: dict,
    min_progress_sec: int = 30,
) -> Optional[EpisodeRef]:
    """Pick the On Deck episode for one series.

    `progress` maps media_file_id -> ProgressRef. Episodes without a playable
    media file are skipped. Season 0 (specials) is ignored unless it is all the
    series has, matching Plex.
    """
    playable = [e for e in episodes if e.media_file_id is not None]
    regular = [e for e in playable if e.season_number > 0]
    if regular:
        playable = regular
    playable.sort(key=lambda e: (e.season_number, e.episode_number))
    if not playable:
        return None

    def prog(e: EpisodeRef) -> Optional[ProgressRef]:
        return progress.get(e.media_file_id)

    # 1. Earliest in-progress (started, not completed) episode.
    for e in playable:
        p = prog(e)
        if p is not None and not p.completed and p.position_sec >= min_progress_sec:
            return e

    # 2. First not-completed episode after the last completed one.
    last_done = -1
    for i, e in enumerate(playable):
        p = prog(e)
        if p is not None and p.completed:
            last_done = i
    if last_done < 0:
        # Nothing completed and nothing in progress: the series isn't started.
        return None
    for e in playable[last_done + 1:]:
        p = prog(e)
        if p is None or not p.completed:
            return e
    return None
