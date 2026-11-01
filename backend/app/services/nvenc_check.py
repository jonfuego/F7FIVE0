"""Is NVENC really usable with this ffmpeg on this machine?

`NVENC_ENABLED=true` says the host has an NVIDIA card, not that the bundled
ffmpeg can open its encoder. An ffmpeg built against a newer NVENC SDK than the
driver offers refuses to start ("Driver does not support the required nvenc API
version. Required: 13.1 Found: 13.0"), every transcode exits at once with -40,
and nothing that needs a transcode plays. GeForce 10-series (Pascal) cards stay
on the 580 driver branch for good, so for them a driver update is no fix.

`nvenc_usable()` runs one tiny encode through the same path a transcode uses
(CUDA upload, `scale_cuda`, `h264_nvenc`) the first time it is asked, and caches
the answer for the life of the process. A failure logs one warning with the
last ffmpeg lines and every caller falls back to libx264. A driver change needs
a service restart to be seen again. Each process (API, stream gateway) asks
for itself.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Optional

from app.config import settings

log = logging.getLogger("f7five0.nvenc_check")

PROBE_TIMEOUT_SEC = 20

_lock = threading.Lock()
_cached: Optional[bool] = None


def probe_args(ffmpeg_bin: str) -> list[str]:
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-f", "lavfi",
        "-i", "color=c=black:s=320x240:r=25:d=0.4",
        "-vf", "format=nv12,hwupload_cuda,scale_cuda=-2:240",
        "-c:v", "h264_nvenc",
        "-frames:v", "5",
        "-f", "null", "-",
    ]


def _probe() -> tuple[bool, str]:
    """Run the test encode. Returns (ok, the last stderr lines)."""
    try:
        proc = subprocess.run(
            probe_args(settings.ffmpeg_bin),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=PROBE_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    tail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()[-6:]
    return proc.returncode == 0, " | ".join(tail)


def nvenc_usable() -> bool:
    """True only when NVENC is switched on AND a test encode worked."""
    global _cached
    if not settings.nvenc_enabled:
        return False
    if _cached is not None:
        return _cached
    with _lock:
        if _cached is None:
            ok, detail = _probe()
            if ok:
                log.info("NVENC test encode ok; hardware transcoding is on")
            else:
                log.warning(
                    "NVENC_ENABLED is true but a test encode with %s failed, so "
                    "transcodes use the CPU (libx264). Usually the NVIDIA driver "
                    "is older than this ffmpeg needs. ffmpeg said: %s",
                    settings.ffmpeg_bin, detail or "(nothing)",
                )
            _cached = ok
    return bool(_cached)


def reset_cache() -> None:
    """Forget the cached answer (tests)."""
    global _cached
    with _lock:
        _cached = None
