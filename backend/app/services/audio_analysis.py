"""Audio analysis: loudness (EBU R128), waveform peaks, gain, and features.

Everything here is designed to run out-of-band from the API (see
`python -m app.cli analyze-audio`). One ffmpeg pass per file for loudness,
one for the waveform. Nothing on this module is called from a request handler.

Design notes:
- Loudness is measured with ffmpeg's `ebur128` filter. We parse the human
  "Summary:" block ffmpeg prints to stderr for the integrated (`I:`) value.
- Gain targets -16 LUFS and is attenuation-only by default: a track quieter
  than the target is NOT boosted (that would clip on already-hot masters and
  costs headroom), unless `allow_boost=True` is passed. Album gain uses the
  album's integrated loudness so intra-album dynamics are preserved.
- Waveform peaks are a downsampled 0..100 int envelope for the scrubber. We
  read raw PCM (mono, 8-bit unsigned via ffmpeg) and bucket it. No numpy
  required; a stdlib loop over ~N samples is plenty for personal-library scale.
- Similarity features are ffmpeg-derived (loudness + a coarse spectral proxy).
  librosa is NOT required; if it is importable and richer features are wanted
  a future pass can guard the import. We keep the hard dependency at ffmpeg.

The parse/compute helpers are pure so they unit-test without ffmpeg on PATH.
"""
from __future__ import annotations

import logging
import math
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from app.config import settings


log = logging.getLogger("f7five0.audio_analysis")


# The loudness target the gain calculation normalizes toward. -16 LUFS is a
# sane middle ground for mixed personal libraries (Spotify uses -14, Apple
# -16, broadcast -23). Chosen per the Phase 2 spec.
TARGET_LUFS = -16.0

# How many waveform buckets to emit. The scrubber never needs more than a
# pixel-per-bucket; ~1000 keeps the JSON small and the render crisp.
DEFAULT_WAVEFORM_BUCKETS = 1000


# ---------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------
def compute_gain_db(integrated_lufs: Optional[float],
                    target_lufs: float = TARGET_LUFS,
                    allow_boost: bool = False) -> Optional[float]:
    """ReplayGain-style adjustment (dB) to bring `integrated_lufs` to target.

    LUFS is a dB-referenced loudness unit, so the raw adjustment is simply
    `target - measured`. Attenuation-only by default: a positive adjustment
    (the track is quieter than target and would be boosted) is clamped to 0
    unless `allow_boost=True`, so normalization never adds gain that could clip
    a hot master or eat headroom. Returns None when loudness is unknown.

    Examples (target -16):
      measured -12.0  -> -4.0  (too loud, attenuate)
      measured -16.0  ->  0.0  (already at target)
      measured -20.0  ->  0.0  (quieter than target, clamped; +4.0 if allow_boost)
    """
    if integrated_lufs is None:
        return None
    if not math.isfinite(integrated_lufs):
        return None
    adjustment = target_lufs - integrated_lufs
    if not allow_boost and adjustment > 0.0:
        return 0.0
    # Round to a hundredth of a dB; sub-0.01 dB is inaudible and keeps the
    # stored value tidy.
    return round(adjustment, 2)


# ---------------------------------------------------------------------------
# ebur128 summary parsing
# ---------------------------------------------------------------------------
# ffmpeg prints something like:
#   [Parsed_ebur128_0 @ ...] Summary:
#
#     Integrated loudness:
#       I:         -14.2 LUFS
#       Threshold: -24.7 LUFS
#     ...
_INTEGRATED_RE = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")


def parse_ebur128_integrated(stderr_text: str) -> Optional[float]:
    """Pull the integrated loudness (LUFS) out of an ffmpeg ebur128 run.

    ffmpeg writes the summary to stderr. We scan for the `I:  <n> LUFS` line in
    the Summary block. Returns None when the pattern is absent (silent file,
    ffmpeg error, unexpected build). A value of `-inf` (dead silence) parses to
    None so the caller stores null rather than a nonsense gain.
    """
    if not stderr_text:
        return None
    # Prefer the last match: the Summary block is emitted after any per-frame
    # lines, and `I:` only appears in the Summary in practice.
    matches = _INTEGRATED_RE.findall(stderr_text)
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except (ValueError, TypeError):
        return None
    if not math.isfinite(value):
        return None
    return value


def measure_loudness(path: str, timeout: float = 120.0) -> Optional[float]:
    """Run ffmpeg ebur128 over `path` and return integrated LUFS, or None.

    Never raises on a missing binary or a probe failure; logs and returns None
    so the CLI can mark the row and move on.
    """
    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-i", path,
        "-map", "a:0",
        "-af", "ebur128=peak=true",
        "-f", "null",
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
        log.warning("ffmpeg ebur128 timed out on %s", path)
        return None
    # ebur128 writes its summary to stderr regardless of return code.
    return parse_ebur128_integrated(proc.stderr or "")


# ---------------------------------------------------------------------------
# Waveform peaks
# ---------------------------------------------------------------------------
def downsample_peaks(samples: bytes, buckets: int = DEFAULT_WAVEFORM_BUCKETS) -> list[int]:
    """Downsample unsigned-8-bit mono PCM into `buckets` peaks scaled 0..100.

    `samples` is raw `u8` PCM (each byte a sample, 128 = silence). We split the
    stream into `buckets` windows and take the max absolute deviation from the
    128 midpoint in each, then scale that 0..127 deviation to 0..100. Returns a
    list no longer than `buckets`; a short/empty input yields a shorter list.
    """
    if buckets <= 0 or not samples:
        return []
    n = len(samples)
    # Scale a u8 midpoint (128) deviation to 0..100. Full scale on the positive
    # side is 127 (value 255); the negative side reaches 128 (value 0), which
    # would round to 101, so we clamp to 100. Both extremes therefore read 100.
    def _scale(dev: int) -> int:
        return min(100, int(round(dev / 127 * 100)))

    if n <= buckets:
        # Fewer samples than buckets: one peak per sample.
        return [_scale(abs(b - 128)) for b in samples]
    window = n / buckets
    peaks: list[int] = []
    for i in range(buckets):
        start = int(i * window)
        end = int((i + 1) * window)
        if end <= start:
            end = start + 1
        chunk = samples[start:end]
        if not chunk:
            peaks.append(0)
            continue
        peak = max(abs(b - 128) for b in chunk)
        peaks.append(_scale(peak))
    return peaks


def compute_waveform(path: str, buckets: int = DEFAULT_WAVEFORM_BUCKETS,
                     timeout: float = 120.0) -> Optional[list[int]]:
    """Extract a downsampled 0..100 waveform envelope for `path`, or None.

    Decodes to low-rate mono u8 PCM via ffmpeg (a 1 kHz mono stream is ample
    detail for a scrubber and keeps the byte volume tiny even for long tracks),
    then buckets it. Never raises; logs and returns None on failure.
    """
    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-i", path,
        "-map", "a:0",
        "-ac", "1",
        "-ar", "1000",
        "-f", "u8",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        log.exception("ffmpeg binary not found at %s", settings.ffmpeg_bin)
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg waveform decode timed out on %s", path)
        return None
    if proc.returncode != 0 or not proc.stdout:
        log.warning("ffmpeg waveform decode failed rc=%s on %s", proc.returncode, path)
        return None
    return downsample_peaks(proc.stdout, buckets)


# ---------------------------------------------------------------------------
# Similarity features
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AudioFeatures:
    """Coarse per-track feature vector for the similarity graph.

    Deliberately small and ffmpeg-derivable. `loudness` is the integrated
    LUFS; `brightness` is a 0..1 proxy for spectral centroid derived from the
    waveform's high-frequency energy fraction; `dynamics` is a 0..1 measure of
    peak variance (a loud-quiet-loud track scores higher than a compressed
    one). These are enough to cluster "similar-sounding" tracks without pulling
    in librosa. If richer features are ever needed, guard a librosa import
    here and extend the vector.
    """

    loudness: float
    brightness: float
    dynamics: float


def features_from_waveform(peaks: list[int],
                           integrated_lufs: Optional[float]) -> AudioFeatures:
    """Derive an AudioFeatures vector from a waveform peaks list + loudness.

    Pure, so it unit-tests without ffmpeg. `brightness` uses the mean
    bucket-to-bucket delta (a fast, decode-free proxy for high-frequency
    content) normalized 0..1. `dynamics` uses the coefficient of variation of
    the peaks. Empty input yields a zeroed-but-valid vector.
    """
    loud = integrated_lufs if (integrated_lufs is not None
                               and math.isfinite(integrated_lufs)) else TARGET_LUFS
    if not peaks:
        return AudioFeatures(loudness=loud, brightness=0.0, dynamics=0.0)

    # Brightness proxy: average absolute delta between adjacent buckets, scaled
    # by the 0..100 range. Choppy envelopes (percussive / bright) score higher.
    if len(peaks) > 1:
        deltas = [abs(peaks[i] - peaks[i - 1]) for i in range(1, len(peaks))]
        brightness = min(1.0, (sum(deltas) / len(deltas)) / 100.0)
    else:
        brightness = 0.0

    mean = sum(peaks) / len(peaks)
    if mean <= 0:
        dynamics = 0.0
    else:
        variance = sum((p - mean) ** 2 for p in peaks) / len(peaks)
        dynamics = min(1.0, (variance ** 0.5) / mean)

    return AudioFeatures(loudness=loud, brightness=brightness, dynamics=dynamics)


def similarity_score(a: AudioFeatures, b: AudioFeatures) -> float:
    """0..1 similarity between two feature vectors (higher = closer).

    Normalizes each dimension to a comparable scale, takes a weighted
    Euclidean distance, and maps distance to a 0..1 score. Loudness is
    normalized over a 0..40 LUFS spread (roughly the practical range);
    brightness and dynamics are already 0..1.
    """
    dl = abs(a.loudness - b.loudness) / 40.0
    dl = min(1.0, dl)
    db_ = abs(a.brightness - b.brightness)
    dd = abs(a.dynamics - b.dynamics)
    # Weighted distance; loudness matters less than timbre for "sounds alike".
    dist = math.sqrt(0.3 * dl * dl + 0.4 * db_ * db_ + 0.3 * dd * dd)
    # dist is in [0, 1] because each weighted term is bounded by its weight and
    # the weights sum to 1. Invert so 0 distance -> score 1.
    return round(max(0.0, 1.0 - dist), 4)
