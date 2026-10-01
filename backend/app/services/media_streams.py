"""Stream enumeration + subtitle extraction for track/audio + video selection.

`probe_streams` runs `ffprobe -show_streams` and returns the subtitle and audio
tracks in the exact shape the app contract expects. `extract_subtitle_vtt`
extracts a single text subtitle stream to WebVTT with ffmpeg; image-based subs
(PGS / VobSub / DVB) cannot be converted to text and are flagged so the route
can 409 with `image_subtitle_burn_required`.

Parse helpers are pure so they unit-test without ffmpeg.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections import OrderedDict
from typing import Optional

from app.config import settings


log = logging.getLogger("f7five0.media_streams")


# Subtitle codecs that are image bitmaps, not text. These cannot be turned into
# WebVTT; the player must burn them into the video instead.
IMAGE_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "dvb_subtitle"}

# Text subtitle codecs ffmpeg can transcode to WebVTT.
TEXT_SUBTITLE_CODECS = {
    "subrip", "srt", "ass", "ssa", "webvtt", "vtt", "mov_text", "text", "microdvd",
}


def is_image_subtitle(codec: Optional[str]) -> bool:
    return (codec or "").lower() in IMAGE_SUBTITLE_CODECS


def _bool_flag(disposition: dict, key: str) -> bool:
    try:
        return bool(int(disposition.get(key, 0)))
    except (TypeError, ValueError):
        return False


def parse_streams(probe_json: dict) -> dict:
    """Shape an ffprobe JSON payload into `{subtitles: [...], audio: [...]}`.

    `index` is the ffmpeg stream index (the absolute index in the container, as
    used by `-map 0:{index}`). Language / title come from stream tags. `forced`
    and `default` come from the disposition block.
    """
    streams = (probe_json or {}).get("streams") or []
    subtitles: list[dict] = []
    audio: list[dict] = []
    for s in streams:
        codec_type = s.get("codec_type")
        tags = s.get("tags") or {}
        disposition = s.get("disposition") or {}
        index = s.get("index")
        if codec_type == "subtitle":
            subtitles.append({
                "index": index,
                "codec": s.get("codec_name"),
                "language": tags.get("language"),
                "title": tags.get("title"),
                "forced": _bool_flag(disposition, "forced"),
                "default": _bool_flag(disposition, "default"),
            })
        elif codec_type == "audio":
            audio.append({
                "index": index,
                "codec": s.get("codec_name"),
                "language": tags.get("language"),
                "channels": s.get("channels"),
                "title": tags.get("title"),
                "default": _bool_flag(disposition, "default"),
            })
    return {"subtitles": subtitles, "audio": audio}


# Successful probes keyed by (path, size, mtime). A probe over SMB on a large
# file costs seconds, and one playback start used to run it two or three times
# (/streams, /stream/start, re-sign). Failures are never cached so a transient
# NAS hiccup retries on the next call.
_PROBE_CACHE_MAX = 512
_probe_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_probe_lock = threading.Lock()


def _probe_key(path: str) -> Optional[tuple]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, st.st_size, int(st.st_mtime))


def clear_probe_cache() -> None:
    with _probe_lock:
        _probe_cache.clear()


def probe_streams(path: str, timeout: float = 30.0) -> Optional[dict]:
    """Return the parsed `{subtitles, audio}` for `path`, cached per file version.

    Returns None on ffprobe failure so the caller can 409/404 appropriately.
    """
    key = _probe_key(path)
    if key is not None:
        with _probe_lock:
            hit = _probe_cache.get(key)
            if hit is not None:
                _probe_cache.move_to_end(key)
                return hit
    result = _run_probe(path, timeout)
    if result is not None and key is not None:
        with _probe_lock:
            _probe_cache[key] = result
            _probe_cache.move_to_end(key)
            while len(_probe_cache) > _PROBE_CACHE_MAX:
                _probe_cache.popitem(last=False)
    return result


def _run_probe(path: str, timeout: float) -> Optional[dict]:
    """Run `ffprobe -show_streams` once (uncached)."""
    cmd = [
        settings.ffprobe_bin,
        "-v", "error",
        "-hide_banner",
        "-print_format", "json",
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
    except FileNotFoundError:
        log.exception("ffprobe binary not found at %s", settings.ffprobe_bin)
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffprobe -show_streams timed out on %s", path)
        return None
    if proc.returncode != 0 or not proc.stdout:
        log.warning("ffprobe -show_streams failed rc=%s on %s", proc.returncode, path)
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return parse_streams(data)


def extract_subtitle_vtt(path: str, stream_index: int, timeout: float = 60.0) -> Optional[str]:
    """Extract text subtitle stream `stream_index` from `path` as WebVTT.

    Returns the WebVTT document as a string, or None on failure. The caller is
    responsible for having already rejected image-based subtitle codecs (this
    function will simply fail for them, since ffmpeg can't transcode a bitmap
    sub to text).
    """
    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-i", path,
        "-map", f"0:{stream_index}",
        "-f", "webvtt",
        "-",
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
    except FileNotFoundError:
        log.exception("ffmpeg binary not found at %s", settings.ffmpeg_bin)
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg subtitle extract timed out on %s idx=%s", path, stream_index)
        return None
    if proc.returncode != 0 or not proc.stdout:
        log.warning(
            "ffmpeg subtitle extract failed rc=%s on %s idx=%s: %s",
            proc.returncode, path, stream_index, (proc.stderr or "")[:200],
        )
        return None
    return proc.stdout
