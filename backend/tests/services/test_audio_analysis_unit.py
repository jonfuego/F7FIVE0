"""Unit tests for the pure audio-analysis helpers (no ffmpeg, no DB).

Covers gain calculation (target -16 LUFS, attenuation-only), ebur128 summary
parsing, waveform downsampling, and the similarity feature/score math.
"""
from __future__ import annotations

import math

from app.services import audio_analysis as aa


# ---- gain (target -16 LUFS, attenuation-only) ------------------------------
def test_gain_attenuates_loud_track():
    # Measured -12 is 4 dB above the -16 target: attenuate by 4 dB.
    assert aa.compute_gain_db(-12.0) == -4.0


def test_gain_zero_at_target():
    assert aa.compute_gain_db(-16.0) == 0.0


def test_gain_clamps_boost_by_default():
    # Quieter than target (-20) would need +4 dB; attenuation-only clamps to 0.
    assert aa.compute_gain_db(-20.0) == 0.0


def test_gain_allows_boost_when_flagged():
    assert aa.compute_gain_db(-20.0, allow_boost=True) == 4.0


def test_gain_custom_target():
    assert aa.compute_gain_db(-10.0, target_lufs=-14.0) == -4.0


def test_gain_none_when_unknown():
    assert aa.compute_gain_db(None) is None


def test_gain_none_when_infinite():
    assert aa.compute_gain_db(float("-inf")) is None


# ---- ebur128 summary parsing -----------------------------------------------
_SUMMARY = """
[Parsed_ebur128_0 @ 0x55] Summary:

  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.7 LUFS

  Loudness range:
    LRA:         6.1 LU
"""


def test_parse_ebur128_integrated():
    assert aa.parse_ebur128_integrated(_SUMMARY) == -14.2


def test_parse_ebur128_missing_returns_none():
    assert aa.parse_ebur128_integrated("no summary here") is None


def test_parse_ebur128_empty_returns_none():
    assert aa.parse_ebur128_integrated("") is None


def test_parse_ebur128_takes_last_match():
    text = "I: -30.0 LUFS\n...\nSummary:\n  I: -14.0 LUFS\n"
    assert aa.parse_ebur128_integrated(text) == -14.0


# ---- waveform downsampling --------------------------------------------------
def test_downsample_empty():
    assert aa.downsample_peaks(b"") == []


def test_downsample_silence_is_zero():
    # 128 is the u8 midpoint (silence).
    samples = bytes([128] * 1000)
    peaks = aa.downsample_peaks(samples, buckets=10)
    assert peaks == [0] * 10


def test_downsample_full_scale_is_100():
    # 255 is max positive deviation (127 from midpoint) -> 100.
    samples = bytes([255] * 1000)
    peaks = aa.downsample_peaks(samples, buckets=10)
    assert all(p == 100 for p in peaks)
    assert len(peaks) == 10


def test_downsample_fewer_samples_than_buckets():
    samples = bytes([128, 255, 0])
    peaks = aa.downsample_peaks(samples, buckets=1000)
    # One peak per sample: 0 (silence), 100 (max +), 100 (max -).
    assert peaks == [0, 100, 100]


def test_downsample_bucket_count_capped():
    samples = bytes(range(256)) * 100  # 25600 samples
    peaks = aa.downsample_peaks(samples, buckets=1000)
    assert len(peaks) == 1000
    assert all(0 <= p <= 100 for p in peaks)


# ---- similarity features + score -------------------------------------------
def test_features_empty_waveform():
    fv = aa.features_from_waveform([], None)
    assert fv.loudness == aa.TARGET_LUFS
    assert fv.brightness == 0.0
    assert fv.dynamics == 0.0


def test_features_flat_waveform_low_brightness():
    fv = aa.features_from_waveform([50] * 100, -14.0)
    assert fv.loudness == -14.0
    assert fv.brightness == 0.0  # no bucket-to-bucket change
    assert fv.dynamics == 0.0    # no variance


def test_features_choppy_waveform_high_brightness():
    peaks = [0, 100] * 50
    fv = aa.features_from_waveform(peaks, -14.0)
    assert fv.brightness > 0.5


def test_similarity_identical_is_one():
    fv = aa.features_from_waveform([10, 20, 30, 20, 10], -14.0)
    assert aa.similarity_score(fv, fv) == 1.0


def test_similarity_different_is_less_than_one():
    a = aa.features_from_waveform([0, 100] * 50, -6.0)
    b = aa.features_from_waveform([50] * 100, -30.0)
    score = aa.similarity_score(a, b)
    assert 0.0 <= score < 1.0


def test_similarity_bounded_zero_one():
    a = aa.AudioFeatures(loudness=0.0, brightness=1.0, dynamics=1.0)
    b = aa.AudioFeatures(loudness=-40.0, brightness=0.0, dynamics=0.0)
    score = aa.similarity_score(a, b)
    assert 0.0 <= score <= 1.0
