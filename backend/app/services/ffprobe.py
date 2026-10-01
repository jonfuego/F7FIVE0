"""ffprobe wrapper. Reads container/codec/dimensions/duration/bitrate from a file.

Returns a structured dict or None on failure. Never raises on a missing file;
the caller flips `scan_state` to `missing` based on the return value.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from app.config import settings


log = logging.getLogger("f7five0.ffprobe")


@dataclass
class ProbeResult:
    container: Optional[str]
    size_bytes: Optional[int]
    duration_sec: Optional[int]
    bitrate_kbps: Optional[int]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    audio_channels: Optional[int]
    width: Optional[int]
    height: Optional[int]


def probe(path: str, timeout: float = 30.0) -> Optional[ProbeResult]:
    """Run ffprobe against `path`. Returns None if the file is missing or probe failed."""
    if not os.path.exists(path):
        return None

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
        # Force UTF-8 decoding; ffprobe output on Windows otherwise tries cp1252
        # and chokes on non-Latin1 bytes in track/artist metadata tags.
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        log.exception("ffprobe binary not found at %s", settings.ffprobe_bin)
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffprobe timed out on %s", path)
        return None

    if proc.returncode != 0:
        log.warning("ffprobe failed rc=%s on %s: %s", proc.returncode, path, (proc.stderr or "")[:200])
        return None

    if not proc.stdout:
        log.warning("ffprobe produced no stdout for %s", path)
        return None

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log.warning("ffprobe returned invalid JSON for %s", path)
        return None

    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    try:
        size_bytes = int(fmt["size"]) if fmt.get("size") else os.path.getsize(path)
    except (ValueError, OSError):
        size_bytes = None

    try:
        duration_sec = int(float(fmt["duration"])) if fmt.get("duration") else None
    except (ValueError, TypeError):
        duration_sec = None

    try:
        bitrate_kbps = int(int(fmt["bit_rate"]) / 1000) if fmt.get("bit_rate") else None
    except (ValueError, TypeError):
        bitrate_kbps = None

    container = _container_from_format(fmt.get("format_name"), path)

    return ProbeResult(
        container=container,
        size_bytes=size_bytes,
        duration_sec=duration_sec,
        bitrate_kbps=bitrate_kbps,
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        audio_channels=_int_or_none((audio or {}).get("channels")),
        width=_int_or_none((video or {}).get("width")),
        height=_int_or_none((video or {}).get("height")),
    )


def _container_from_format(format_name: Optional[str], path: str) -> Optional[str]:
    """ffprobe's `format_name` is usually a comma-separated alias list (e.g. 'matroska,webm').
    Prefer the file extension, which is what browsers and MIME guessing actually care about.
    """
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext:
        return ext
    if format_name:
        return format_name.split(",")[0].strip() or None
    return None


def _int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
