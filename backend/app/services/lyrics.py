"""Lyrics resolution: embedded tags + `.lrc` sidecar. No third-party service.

Two sources, in priority order:
1. An `.lrc` sidecar next to the media file (same stem). If it carries LRC
   timestamps (`[mm:ss.xx]`) we return synced lines; otherwise its raw text.
2. Embedded lyric tags read via ffprobe format/stream tags (`lyrics`,
   `LYRICS`, `unsyncedlyrics`, `USLT`, ...). These are almost always plain
   text, but if a tag happens to carry LRC timestamps we parse them too.

We never call an external lyrics provider. The endpoint returns the contract
shape: `{synced, lines, text, source}` with nulls when nothing is found.

The parse helpers are pure so they unit-test without ffmpeg or real files.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from app.config import settings


log = logging.getLogger("f7five0.lyrics")


# `[mm:ss.xx]` or `[mm:ss]` or `[mm:ss.xxx]`, optionally several per line for
# repeated lines. Also tolerate `[m:ss]`.
_LRC_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")

# ID3 / Vorbis / MP4 tag keys that carry lyrics, lower-cased for matching.
_LYRIC_TAG_KEYS = (
    "lyrics",
    "unsyncedlyrics",
    "unsynced lyrics",
    "uslt",
    "lyrics-eng",
    "lyrics-xxx",
    "©lyr",
)


@dataclass(frozen=True)
class LyricsResult:
    synced: bool
    lines: Optional[list[dict]]  # [{time_ms:int, text:str}, ...] when synced
    text: Optional[str]
    source: Optional[str]        # "embedded" | "lrc" | None


EMPTY = LyricsResult(synced=False, lines=None, text=None, source=None)


def _ts_to_ms(minutes: str, seconds: str, frac: Optional[str]) -> int:
    total = int(minutes) * 60_000 + int(seconds) * 1000
    if frac:
        # Two-digit fraction is centiseconds; three-digit is milliseconds.
        if len(frac) == 3:
            total += int(frac)
        elif len(frac) == 2:
            total += int(frac) * 10
        else:  # single digit -> tenths
            total += int(frac) * 100
    return total


def parse_lrc(content: str) -> LyricsResult:
    """Parse LRC text into a LyricsResult.

    Handles multiple timestamps per line (repeated choruses), ID-tag lines like
    `[ar:Artist]` / `[ti:Title]` (skipped), and plain untimed lines. When no
    timestamped lines are found, returns the stripped raw text as unsynced.
    Lines are sorted by time and returned as `{time_ms, text}` dicts.
    """
    if not content:
        return EMPTY

    timed: list[dict] = []
    saw_timestamp = False
    for raw_line in content.splitlines():
        tags = list(_LRC_TAG_RE.finditer(raw_line))
        if not tags:
            continue
        # Everything after the last timestamp on the line is the lyric text.
        text = raw_line[tags[-1].end():].strip()
        for m in tags:
            ms = _ts_to_ms(m.group(1), m.group(2), m.group(3))
            saw_timestamp = True
            timed.append({"time_ms": ms, "text": text})

    if saw_timestamp and timed:
        timed.sort(key=lambda d: d["time_ms"])
        # A plain concatenation is handy for clients that don't render synced.
        plain = "\n".join(d["text"] for d in timed if d["text"])
        return LyricsResult(
            synced=True, lines=timed, text=plain or None, source="lrc",
        )

    # No timestamps: treat the whole thing as plain lyrics.
    stripped = content.strip()
    if not stripped:
        return EMPTY
    return LyricsResult(synced=False, lines=None, text=stripped, source="lrc")


def lrc_sidecar_path(media_path: str) -> str:
    """Return the `.lrc` path next to `media_path` (same stem)."""
    stem, _ext = os.path.splitext(media_path)
    return stem + ".lrc"


def read_lrc_sidecar(media_path: str) -> Optional[LyricsResult]:
    """Read + parse the `.lrc` sidecar next to `media_path`, or None if absent.

    Tolerates UTF-8 with or without BOM; falls back to latin-1 so a legacy
    sidecar never crashes the endpoint.
    """
    path = lrc_sidecar_path(media_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            content = fh.read()
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="latin-1") as fh:
                content = fh.read()
        except OSError:
            return None
    except OSError:
        return None
    result = parse_lrc(content)
    return result if result.source is not None else None


def extract_embedded_lyrics_text(tags: dict) -> Optional[str]:
    """Find a lyrics value in an ffprobe tags dict (case-insensitive keys)."""
    if not tags:
        return None
    lowered = {str(k).lower(): v for k, v in tags.items()}
    for key in _LYRIC_TAG_KEYS:
        val = lowered.get(key)
        if isinstance(val, str) and val.strip():
            return val
    # Some muxers prefix the language, e.g. `lyrics-eng`; catch any lyrics* key.
    for k, v in lowered.items():
        if k.startswith("lyric") and isinstance(v, str) and v.strip():
            return v
    return None


def _probe_tags(path: str, timeout: float = 30.0) -> dict:
    """Return merged format + stream tags via ffprobe. Empty dict on failure."""
    import json

    cmd = [
        settings.ffprobe_bin,
        "-v", "error",
        "-hide_banner",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    tags: dict = {}
    fmt = data.get("format") or {}
    tags.update(fmt.get("tags") or {})
    for stream in data.get("streams") or []:
        tags.update(stream.get("tags") or {})
    return tags


def read_embedded_lyrics(path: str) -> Optional[LyricsResult]:
    """Read embedded lyric tags for `path`, or None if none present.

    An embedded value carrying LRC timestamps is parsed as synced; otherwise it
    is returned as plain unsynced text. `source` is always "embedded".
    """
    tags = _probe_tags(path)
    text = extract_embedded_lyrics_text(tags)
    if not text:
        return None
    # An embedded tag might itself be LRC-formatted.
    if _LRC_TAG_RE.search(text):
        parsed = parse_lrc(text)
        if parsed.synced:
            return LyricsResult(
                synced=True, lines=parsed.lines, text=parsed.text,
                source="embedded",
            )
    return LyricsResult(synced=False, lines=None, text=text.strip(), source="embedded")


def resolve_lyrics(media_path: str) -> LyricsResult:
    """Resolve lyrics for a media file: `.lrc` sidecar first, then embedded.

    Never raises; returns EMPTY when nothing is found or the file is gone.
    """
    if not media_path:
        return EMPTY
    sidecar = read_lrc_sidecar(media_path)
    if sidecar is not None:
        return sidecar
    embedded = read_embedded_lyrics(media_path)
    if embedded is not None:
        return embedded
    return EMPTY
