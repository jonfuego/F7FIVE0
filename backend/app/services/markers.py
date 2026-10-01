"""Intro/credits marker detection via an ffmpeg black + silence heuristic.

This is the conservative v1 the ux-extras handoff scopes: detect a region
near the start (intro) and end (credits) of an episode that is BOTH black
and silent, and store it as a marker the player can offer to skip. Black AND
silent together is a scene-transition gap, so skipping it can never skip real
content. False negatives are acceptable; false positives (skipping content)
are the thing to avoid, hence the intersection requirement.

The thresholds below are the tuning surface. Bias conservative. After running
against a couple of real test series, widen the windows or relax the floors if
too many episodes come back with no marker. CPU-decode only; the caller
throttles to one analysis at a time so live streams keep their NVENC headroom.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.markers import (
    KIND_CREDITS, KIND_INTRO, SOURCE_AUTO, MediaMarker,
)
from app.models.media_file import MediaFile, MediaKind, ScanState


log = logging.getLogger("f7five0.markers")

# --- tuning surface --------------------------------------------------------
_SILENCE_NOISE = "-30dB"      # below this RMS counts as silence
_SILENCE_MIN_SEC = 0.3        # silencedetect d=
_BLACK_MIN_SEC = 0.2          # blackdetect d=
_BLACK_PIX_TH = 0.10          # blackdetect pix_th=
_INTRO_WINDOW_FRAC = 0.25     # scan the first quarter for an intro
_INTRO_WINDOW_CAP_SEC = 300   # but never more than 5 minutes
_CREDITS_WINDOW_FRAC = 0.10   # scan the last tenth for credits
_MIN_MARKER_SEC = 1.0         # ignore black+silent gaps shorter than this
_MIN_FILE_SEC = 120           # files shorter than this are not worth scanning
_FFMPEG_TIMEOUT = 180.0       # per-window decode ceiling

_BLACK_RE = re.compile(r"black_start:(?P<start>[\d.]+)\s+black_end:(?P<end>[\d.]+)")
_SIL_START_RE = re.compile(r"silence_start:\s*(?P<start>[\d.]+)")
_SIL_END_RE = re.compile(r"silence_end:\s*(?P<end>[\d.]+)")

Interval = tuple[float, float]


def analyze_episode_files(
    db: Session, *, series_id: Optional[uuid.UUID] = None, force: bool = False,
) -> dict:
    """Analyze ready episode files, optionally scoped to one series.

    Skips files that already have markers unless force=True. Runs one ffmpeg
    at a time (this function is invoked from a single scheduler job).
    Returns a small summary the admin response can echo."""
    stmt = (
        select(MediaFile)
        .where(MediaFile.kind == MediaKind.episode)
        .where(MediaFile.scan_state == ScanState.ready)
    )
    files = list(db.scalars(stmt))

    scanned = 0
    markers_written = 0
    skipped_existing = 0
    for mf in files:
        if series_id is not None and not _belongs_to_series(db, mf, series_id):
            continue
        if not force and _has_markers(db, mf.id):
            skipped_existing += 1
            continue
        scanned += 1
        markers_written += analyze_media_file(db, mf, force=force)
    db.commit()
    summary = {
        "scanned": scanned,
        "markers_written": markers_written,
        "skipped_existing": skipped_existing,
    }
    log.info("marker analysis done: %s", summary)
    return summary


def analyze_media_file(db: Session, mf: MediaFile, *, force: bool = False) -> int:
    """Detect intro/credits on one file and upsert markers. Returns the
    number of markers written (0, 1, or 2)."""
    path = mf.path
    if not path or not os.path.exists(path):
        log.warning("marker analysis skipped, missing file: %s", path)
        return 0
    duration = mf.duration_sec or 0
    if duration < _MIN_FILE_SEC:
        return 0

    written = 0

    intro_end = min(duration * _INTRO_WINDOW_FRAC, _INTRO_WINDOW_CAP_SEC)
    intro = _detect_gap(path, 0.0, intro_end)
    if intro is not None:
        _upsert_marker(db, mf.id, KIND_INTRO, intro, force=force)
        written += 1

    credits_start = duration * (1.0 - _CREDITS_WINDOW_FRAC)
    credits = _detect_gap(path, credits_start, float(duration))
    if credits is not None:
        _upsert_marker(db, mf.id, KIND_CREDITS, credits, force=force)
        written += 1

    return written


# ---------------------------------------------------------------------------
# Detection internals
# ---------------------------------------------------------------------------
def _detect_gap(path: str, win_start: float, win_end: float) -> Optional[Interval]:
    """Return the longest region inside the window that is both black and
    silent, or None. Times are absolute (window start added back)."""
    win_len = win_end - win_start
    if win_len < _MIN_MARKER_SEC:
        return None
    black, silence = _run_ffmpeg_detect(path, win_start, win_len)
    overlaps = _intersect(black, silence)
    overlaps = [(s, e) for (s, e) in overlaps if (e - s) >= _MIN_MARKER_SEC]
    if not overlaps:
        return None
    # Longest qualifying gap wins.
    best = max(overlaps, key=lambda iv: iv[1] - iv[0])
    return (round(win_start + best[0]), round(win_start + best[1]))


def _run_ffmpeg_detect(
    path: str, win_start: float, win_len: float,
) -> tuple[list[Interval], list[Interval]]:
    """Run blackdetect + silencedetect over a window. Returns (black, silence)
    interval lists with times relative to the window start."""
    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner", "-nostats",
        "-ss", f"{win_start:.3f}",
        "-t", f"{win_len:.3f}",
        "-i", path,
        "-vf", f"blackdetect=d={_BLACK_MIN_SEC}:pix_th={_BLACK_PIX_TH}",
        "-af", f"silencedetect=noise={_SILENCE_NOISE}:d={_SILENCE_MIN_SEC}",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_FFMPEG_TIMEOUT, check=False,
        )
    except FileNotFoundError:
        log.exception("ffmpeg binary not found at %s", settings.ffmpeg_bin)
        return [], []
    except subprocess.TimeoutExpired:
        log.warning("marker ffmpeg timed out on %s", path)
        return [], []

    # blackdetect and silencedetect both log to stderr.
    text = proc.stderr or ""
    black: list[Interval] = [
        (float(m.group("start")), float(m.group("end")))
        for m in _BLACK_RE.finditer(text)
    ]
    silence: list[Interval] = []
    pending: Optional[float] = None
    for line in text.splitlines():
        ms = _SIL_START_RE.search(line)
        if ms:
            pending = float(ms.group("start"))
            continue
        me = _SIL_END_RE.search(line)
        if me and pending is not None:
            silence.append((pending, float(me.group("end"))))
            pending = None
    return black, silence


def _intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    """Overlapping sub-intervals between two interval lists."""
    out: list[Interval] = []
    for (a0, a1) in a:
        for (b0, b1) in b:
            lo = max(a0, b0)
            hi = min(a1, b1)
            if hi > lo:
                out.append((lo, hi))
    return out


def _upsert_marker(
    db: Session, media_file_id: uuid.UUID, kind: str, interval: Interval,
    *, force: bool,
) -> None:
    start_sec, end_sec = int(interval[0]), int(interval[1])
    row = db.scalar(
        select(MediaMarker).where(
            MediaMarker.media_file_id == media_file_id,
            MediaMarker.kind == kind,
        )
    )
    if row is None:
        db.add(MediaMarker(
            media_file_id=media_file_id, kind=kind,
            start_sec=start_sec, end_sec=end_sec, source=SOURCE_AUTO,
        ))
    elif force or row.source == SOURCE_AUTO:
        # Never clobber a manual marker unless forced.
        row.start_sec = start_sec
        row.end_sec = end_sec
        row.source = SOURCE_AUTO
    db.flush()


def _has_markers(db: Session, media_file_id: uuid.UUID) -> bool:
    return db.scalar(
        select(MediaMarker.id).where(
            MediaMarker.media_file_id == media_file_id
        ).limit(1)
    ) is not None


def _belongs_to_series(db: Session, mf: MediaFile, series_id: uuid.UUID) -> bool:
    """True when this episode media file's parent episode is in the series."""
    from app.models.tv import Episode

    ep = db.get(Episode, mf.ref_id)
    return ep is not None and ep.series_id == series_id
