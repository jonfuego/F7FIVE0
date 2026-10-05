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


# ---------------------------------------------------------------------------
# Shared backfill engine
#
# Both the `analyze-audio` CLI and the scheduler's automatic job call these.
# The per-track work, album-gain pass, and similarity rebuild live here once so
# the CLI and the job never drift apart. The CLI adds argument parsing, logging,
# and a throttle sleep around `analyze_track`; the scheduler job calls the same
# functions one track at a time at low priority. Nothing here runs on a request
# path; each ffmpeg pass is a subprocess.
# ---------------------------------------------------------------------------
# Default number of similarity edges to keep per track.
DEFAULT_SIMILAR_TOP_N = 25

# Statuses `analyze_track` returns so callers can total them.
STATUS_ANALYZED = "analyzed"
STATUS_SKIPPED = "skipped"
STATUS_NO_FILE = "no_file"
STATUS_FAILED = "failed"


def tracks_needing_analysis(db) -> list:
    """Track ids that have NO analysis row yet (the automatic job's working set).

    A track is "needing analysis" when no `track_audio_analysis` row exists for
    it, or the row exists but was never stamped `analyzed_at` (a half-written or
    failed row). Returns ids ordered by track id for a stable, resumable walk.
    This is the exact set the scheduler job fills; it never re-touches tracks
    the CLI already analyzed.
    """
    from sqlalchemy import select

    from app.models.audio_analysis import TrackAudioAnalysis
    from app.models.music import Track

    analyzed_ids = set(db.scalars(
        select(TrackAudioAnalysis.track_id)
        .where(TrackAudioAnalysis.analyzed_at.isnot(None))
    ))
    all_ids = list(db.scalars(select(Track.id).order_by(Track.id)))
    return [tid for tid in all_ids if tid not in analyzed_ids]


def analysis_progress(db) -> dict:
    """Return {'analyzed': int, 'total': int} for the music library.

    `total` is every track; `analyzed` is every track with a stamped analysis
    row. The admin progress readout renders `analyzed / total`.
    """
    from sqlalchemy import func, select

    from app.models.audio_analysis import TrackAudioAnalysis
    from app.models.music import Track

    total = int(db.scalar(select(func.count()).select_from(Track)) or 0)
    analyzed = int(db.scalar(
        select(func.count())
        .select_from(TrackAudioAnalysis)
        .where(TrackAudioAnalysis.analyzed_at.isnot(None))
    ) or 0)
    return {"analyzed": analyzed, "total": total}


def analyze_track(db, track_id, *, target_lufs: float = TARGET_LUFS,
                  allow_boost: bool = False, force: bool = False) -> str:
    """Analyze ONE track: loudness, waveform, track gain -> a stamped row.

    Returns one of STATUS_ANALYZED / STATUS_SKIPPED / STATUS_NO_FILE /
    STATUS_FAILED. Does NOT commit; the caller owns the transaction boundary so
    it can batch commits and throttle between files. Skips a track that already
    has a stamped row unless `force`. This is the single per-track unit of work
    shared by the CLI and the scheduler job.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.audio_analysis import ANALYSIS_VERSION, TrackAudioAnalysis
    from app.models.media_file import MediaFile, MediaKind, ScanState
    from app.services import path_map

    row = db.scalar(
        select(TrackAudioAnalysis).where(TrackAudioAnalysis.track_id == track_id)
    )
    if row is not None and row.analyzed_at is not None and not force:
        return STATUS_SKIPPED

    mf = db.scalar(
        select(MediaFile)
        .where(
            MediaFile.kind == MediaKind.track,
            MediaFile.ref_id == track_id,
            MediaFile.scan_state == ScanState.ready,
        )
        .order_by(MediaFile.id)
        .limit(1)
    )
    if mf is None:
        return STATUS_NO_FILE

    path = path_map.translate(mf.path) or mf.path
    lufs = measure_loudness(path)
    peaks = compute_waveform(path)
    if lufs is None and peaks is None:
        return STATUS_FAILED

    gain = compute_gain_db(lufs, target_lufs=target_lufs, allow_boost=allow_boost)
    if row is None:
        row = TrackAudioAnalysis(track_id=track_id)
        db.add(row)
    row.media_file_id = mf.id
    row.integrated_lufs = lufs
    row.track_gain_db = gain
    row.waveform_peaks = peaks
    row.analysis_version = ANALYSIS_VERSION
    row.analyzed_at = datetime.now(timezone.utc)
    db.flush()
    return STATUS_ANALYZED


def recompute_album_gains(db, analyzed_track_ids, *,
                          target_lufs: float = TARGET_LUFS,
                          allow_boost: bool = False) -> None:
    """Set album_gain_db for every album touched by `analyzed_track_ids`.

    Album gain normalizes each album toward the target using the album's own
    integrated loudness (mean of its tracks' LUFS as a cheap stand-in), so
    intra-album dynamics are preserved. Does NOT commit.
    """
    from sqlalchemy import select

    from app.models.audio_analysis import TrackAudioAnalysis
    from app.models.music import Track

    touched_albums = set()
    for tid in analyzed_track_ids:
        t = db.get(Track, tid)
        if t is not None:
            touched_albums.add(t.album_id)
    for album_id in touched_albums:
        album_track_ids = list(db.scalars(
            select(Track.id).where(Track.album_id == album_id)
        ))
        rows = list(db.scalars(
            select(TrackAudioAnalysis)
            .where(TrackAudioAnalysis.track_id.in_(album_track_ids))
        ))
        lufs_vals = [r.integrated_lufs for r in rows if r.integrated_lufs is not None]
        if not lufs_vals:
            continue
        album_lufs = sum(lufs_vals) / len(lufs_vals)
        album_gain = compute_gain_db(
            album_lufs, target_lufs=target_lufs, allow_boost=allow_boost,
        )
        for r in rows:
            r.album_gain_db = album_gain


def rebuild_similarity(db, seed_track_ids, *,
                       top_n: int = DEFAULT_SIMILAR_TOP_N,
                       force: bool = False) -> int:
    """Rebuild similarity edges for the given seed tracks (top-N per seed).

    Features come from every analyzed track in the library so the graph is
    complete, but edges are rewritten only for `seed_track_ids` (or all analyzed
    tracks when `force`) to keep an incremental run cheap. Returns the number of
    seed tracks whose edges were rebuilt. Does NOT commit.
    """
    from sqlalchemy import select

    from app.models.audio_analysis import TrackAudioAnalysis, TrackSimilarity

    all_rows = list(db.scalars(
        select(TrackAudioAnalysis).where(TrackAudioAnalysis.analyzed_at.isnot(None))
    ))
    feats = [
        (r.track_id, features_from_waveform(r.waveform_peaks or [], r.integrated_lufs))
        for r in all_rows
    ]
    seeds = set(seed_track_ids)
    if len(feats) < 2 or (not force and not seeds):
        return 0
    if force:
        seeds = {t for t, _ in feats}

    rebuilt = 0
    for seed_id, seed_fv in feats:
        if seed_id not in seeds:
            continue
        scored = [
            (other_id, similarity_score(seed_fv, other_fv))
            for other_id, other_fv in feats
            if other_id != seed_id
        ]
        scored.sort(key=lambda p: p[1], reverse=True)
        top = scored[:top_n]
        db.query(TrackSimilarity).filter(
            TrackSimilarity.track_id == seed_id
        ).delete(synchronize_session=False)
        for other_id, score in top:
            db.add(TrackSimilarity(
                track_id=seed_id, similar_track_id=other_id, score=score,
            ))
        rebuilt += 1
    return rebuilt
