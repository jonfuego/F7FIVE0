"""NVENC is used only when a real test encode works (services/nvenc_check.py).

The 1.0.18 Setup ships ffmpeg 9.0.2, which needs NVIDIA driver 610 or newer.
A GTX 1060 on driver 582.28 refused the encoder ("Required: 13.1 Found:
13.0"), every transcode exited -40 and no movie with AC3 audio played.
"""
from __future__ import annotations

import logging
import subprocess

from app.config import settings
from app.services import nvenc_check


def test_off_never_probes(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "nvenc_enabled", False)
    monkeypatch.setattr(nvenc_check, "_probe", lambda: calls.append(1) or (True, ""))
    assert nvenc_check.nvenc_usable() is False
    assert calls == []


def test_failed_probe_falls_back_and_is_cached(monkeypatch, caplog):
    calls = []

    def bad():
        calls.append(1)
        return False, "Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0"

    monkeypatch.setattr(settings, "nvenc_enabled", True)
    monkeypatch.setattr(nvenc_check, "_probe", bad)
    with caplog.at_level(logging.WARNING, logger="f7five0.nvenc_check"):
        assert nvenc_check.nvenc_usable() is False
        assert nvenc_check.nvenc_usable() is False
    assert calls == [1]
    assert "Required: 13.1" in caplog.text
    assert "libx264" in caplog.text


def test_working_probe_turns_nvenc_on(monkeypatch):
    monkeypatch.setattr(settings, "nvenc_enabled", True)
    monkeypatch.setattr(nvenc_check, "_probe", lambda: (True, ""))
    assert nvenc_check.nvenc_usable() is True


def test_real_probe_reports_failure_and_missing_binary(monkeypatch):
    # Undo the conftest stub and run the real _probe against fake binaries.
    import importlib
    real = importlib.reload(nvenc_check)
    try:
        monkeypatch.setattr(settings, "ffmpeg_bin", "/nonexistent/ffmpeg")
        ok, detail = real._probe()
        assert ok is False and "FileNotFoundError" in detail

        class P:
            returncode = 4294967256
            stderr = b"line1\n[h264_nvenc] The minimum required Nvidia driver for nvenc is 610.00 or newer\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
        ok, detail = real._probe()
        assert ok is False and "610.00" in detail
    finally:
        real.reset_cache()


def test_probe_uses_the_transcode_path():
    args = nvenc_check.probe_args("ffmpeg")
    joined = " ".join(args)
    assert "h264_nvenc" in joined and "scale_cuda" in joined and "hwupload_cuda" in joined


def test_transcode_argv_and_rungs_follow_the_probe(monkeypatch):
    """With the probe failing, the stream gateway serves one CPU rung."""
    from app import stream
    from app.services.playback import VARIANT_LADDER

    monkeypatch.setattr(settings, "nvenc_enabled", True)
    monkeypatch.setattr(nvenc_check, "_probe", lambda: (False, "x"))

    class MF:
        height = 1080
        width = 1920
        video_codec = "h264"
        audio_codec = "ac3"
        container = "mkv"
        kind = None
        path = "x.mkv"

    import app.stream as st
    monkeypatch.setattr(st, "is_audio_only", lambda mf: False)
    variants = stream._variants_for(MF(), "")
    assert len(variants) == 1
    assert all(v in VARIANT_LADDER for v in variants)
