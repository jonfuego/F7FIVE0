"""The shared long-form helpers (services/longform.py): skip, played rule,
chapter at a time, state label, speed clamp."""
from __future__ import annotations

import pytest

from app.services import longform


def test_constants():
    assert longform.SKIP_BACK_SEC == 15 and longform.SKIP_FORWARD_SEC == 30
    assert longform.PLAYED_TAIL_SEC == 30 and longform.PLAYED_FRACTION == 0.95
    assert longform.MIN_SPEED == 0.5 and longform.MAX_SPEED == 3.0


@pytest.mark.parametrize("pos, dur, expected", [
    (0, 100, 0), (10, 100, 0), (50, 100, 35), (50, 0, 35), (10, None, 0),
])
def test_skip_back_bounds(pos, dur, expected):
    assert longform.skip_back(pos, dur) == expected


@pytest.mark.parametrize("pos, dur, expected", [
    (0, 100, 30), (80, 100, 100), (100, 100, 100), (10, 0, 40), (10, None, 40),
])
def test_skip_forward_bounds(pos, dur, expected):
    assert longform.skip_forward(pos, dur) == expected


@pytest.mark.parametrize("pos, dur, played", [
    (0, 100, False), (50, 100, False), (69, 100, False), (70, 100, True), (100, 100, True),
    (6839, 7200, False), (6840, 7200, True), (269, 300, False), (270, 300, True),
    (10, 0, False), (10, None, False), (5000, 0, False),
])
def test_is_played(pos, dur, played):
    assert longform.is_played(pos, dur) is played


def test_chapter_at():
    ch = [{"start_sec": 0, "title": "A"}, {"start_sec": 60, "title": "B"}, {"start_sec": 300, "title": "C"}]
    assert longform.chapter_at(ch, 0) == 0
    assert longform.chapter_at(ch, 59.9) == 0
    assert longform.chapter_at(ch, 60) == 1
    assert longform.chapter_at(ch, 10_000) == 2
    assert longform.chapter_at(ch, -5) == 0
    assert longform.chapter_at([], 10) is None
    assert longform.chapter_at([{"start_sec": 30, "title": "late"}], 10) is None


def test_episode_state():
    assert longform.state_for(position_sec=0, played=False) == {"kind": "new"}
    assert longform.state_for(position_sec=120, played=False) == {"kind": "in_progress", "position_sec": 120}
    assert longform.state_for(position_sec=120, played=True) == {"kind": "played"}
    assert longform.state_for(position_sec=None, played=False) == {"kind": "new"}


def test_clamp_speed():
    assert longform.clamp_speed(1) == 1.0
    assert longform.clamp_speed(0.25) == 0.5
    assert longform.clamp_speed(4) == 3.0
    assert longform.clamp_speed("bad") == 1.0
