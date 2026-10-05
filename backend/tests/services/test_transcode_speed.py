"""Transcode speed: parse ffmpeg -progress output into a realtime factor.

Feeds sample ffmpeg `-progress` blocks (the key=value stream ffmpeg writes to
the pipe) into the pure parser and asserts the extracted speed, including a
below-1.0x "server can't keep up" case. Also checks the ffmpeg argv carries
the progress flags while keeping `-loglevel warning`, and that a job's
below-realtime clock behaves.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.services import transcoder
from app.services.playback import VARIANT_LADDER


# A fast encode: ffmpeg is well ahead of realtime. One -progress block.
PROGRESS_FAST = """\
bitrate=2200.1kbits/s
total_size=5500000
out_time_us=24000000
out_time_ms=24000000
out_time=00:00:24.000000
dup_frames=0
drop_frames=0
speed=3.12x
progress=continue
"""

# A slow encode on a weak CPU: ffmpeg is behind realtime (<1.0x).
PROGRESS_SLOW = """\
bitrate= 900.0kbits/s
total_size=1200000
out_time_us=12000000
out_time_ms=12000000
out_time=00:00:12.000000
dup_frames=0
drop_frames=4
speed=0.47x
progress=continue
"""

# Startup block before ffmpeg has a measurement: speed=N/A.
PROGRESS_NA = """\
bitrate=N/A
total_size=N/A
out_time_us=N/A
out_time_ms=N/A
out_time=N/A
speed=N/A
progress=continue
"""

# Two blocks concatenated (as a reader buffer might accumulate): the last
# speed wins.
PROGRESS_TWO_BLOCKS = PROGRESS_SLOW + PROGRESS_FAST

# An older ffmpeg that omits speed= entirely; must fall back to out_time.
PROGRESS_NO_SPEED = """\
bitrate=1500.0kbits/s
total_size=3000000
out_time_us=30000000
out_time_ms=30000000
out_time=00:00:30.000000
progress=continue
"""


def _v(label: str):
    return next(v for v in VARIANT_LADDER if v.label == label)


# -- pure parser ------------------------------------------------------------
def test_parse_speed_fast() -> None:
    assert transcoder.parse_progress_speed(PROGRESS_FAST) == 3.12


def test_parse_speed_below_realtime() -> None:
    speed = transcoder.parse_progress_speed(PROGRESS_SLOW)
    assert speed == 0.47
    assert speed < transcoder.REALTIME_FACTOR  # the "can't keep up" case


def test_parse_speed_na_is_unknown() -> None:
    assert transcoder.parse_progress_speed(PROGRESS_NA) is None


def test_parse_speed_last_block_wins() -> None:
    # SLOW then FAST: the most recent measurement (FAST) is reported.
    assert transcoder.parse_progress_speed(PROGRESS_TWO_BLOCKS) == 3.12


def test_parse_speed_missing_returns_none() -> None:
    assert transcoder.parse_progress_speed(PROGRESS_NO_SPEED) is None


def test_parse_out_time_sec() -> None:
    # out_time_us is microseconds: 30_000_000 us -> 30.0 s.
    assert transcoder.parse_out_time_sec(PROGRESS_NO_SPEED) == 30.0
    assert transcoder.parse_out_time_sec(PROGRESS_NA) is None


def test_speed_from_out_time() -> None:
    # 30s of output in 60s wall time = 0.5x (behind realtime).
    assert transcoder.speed_from_out_time(30.0, 60.0) == 0.5
    # 60s of output in 30s wall time = 2.0x (ahead).
    assert transcoder.speed_from_out_time(60.0, 30.0) == 2.0
    # No wall time yet -> unknown.
    assert transcoder.speed_from_out_time(10.0, 0.0) is None


def test_fallback_speed_when_no_speed_line() -> None:
    # Mirrors the reader's fallback: no speed= -> compute from out_time/wall.
    speed = transcoder.parse_progress_speed(PROGRESS_NO_SPEED)
    assert speed is None
    out_time = transcoder.parse_out_time_sec(PROGRESS_NO_SPEED)
    assert out_time == 30.0
    assert transcoder.speed_from_out_time(out_time, 20.0) == 1.5


# -- job below-realtime clock ----------------------------------------------
def _job() -> transcoder.TranscodeJob:
    class _FakeProc:
        def poll(self):
            return None

    return transcoder.TranscodeJob(
        user_id=uuid.uuid4(),
        media_file_id=uuid.uuid4(),
        variant=_v("high"),
        source_path=Path("f.mkv"),
        out_dir=Path("."),
        proc=_FakeProc(),
    )


def test_record_speed_tracks_below_realtime_window() -> None:
    job = _job()
    # Ahead of realtime: no window open.
    assert job.record_speed(2.0, now=100.0) == 0
    assert job.below_realtime_sec(now=130.0) == 0
    # Drops below realtime at t=200: clock starts.
    assert job.record_speed(0.8, now=200.0) == 0
    # Still below 10s later.
    assert job.record_speed(0.7, now=210.0) == 10
    # Still below 35s after the drop -> past the 30s warn threshold.
    assert job.record_speed(0.6, now=235.0) == 35
    assert job.below_realtime_sec(now=235.0) == 35
    # Recovers: window resets.
    assert job.record_speed(1.5, now=240.0) == 0
    assert job.below_realtime_sec(now=300.0) == 0


# -- ffmpeg argv ------------------------------------------------------------
def test_ffmpeg_args_carry_progress_and_keep_warning(tmp_path: Path) -> None:
    args = transcoder._build_ffmpeg_args(
        tmp_path / "src.mkv", _v("high"), tmp_path / "out", nvenc=False,
    )
    # -progress emits a parseable stream; -stats_period sets the cadence.
    assert "-progress" in args
    assert args[args.index("-progress") + 1] == "pipe:1"
    assert "-stats_period" in args
    assert args[args.index("-stats_period") + 1] == str(transcoder.STATS_PERIOD_SEC)
    # -loglevel warning must be preserved per the repo rules.
    assert "-loglevel" in args
    assert args[args.index("-loglevel") + 1] == "warning"
