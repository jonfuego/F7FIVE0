"""CPU-only servers offer one HLS rung per stream, so no player can switch
quality on its own and start a second encode."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.playback import VARIANT_LADDER, single_rung_for_cpu
from app.services.track_opts import resolve_track_opts


def _labels(variants):
    return [v.label for v in variants]


def test_default_is_720_on_a_1080_source() -> None:
    assert _labels(single_rung_for_cpu(VARIANT_LADDER, None)) == ["medium"]


def test_viewer_pick_wins() -> None:
    assert _labels(single_rung_for_cpu(VARIANT_LADDER, 1080)) == ["high"]
    assert _labels(single_rung_for_cpu(VARIANT_LADDER, 480)) == ["low"]


def test_small_source_gets_its_top_rung() -> None:
    low_only = tuple(v for v in VARIANT_LADDER if v.label == "low")
    assert _labels(single_rung_for_cpu(low_only, None)) == ["low"]
    assert _labels(single_rung_for_cpu(low_only, 1080)) == ["low"]


@pytest.mark.parametrize(
    "nvenc, o, expected",
    [
        (False, "", ["medium"]),
        (False, "q1080", ["high"]),
        (False, "q480", ["low"]),
        (True, "", ["high", "medium", "low"]),
        (True, "q720", ["medium", "low"]),
    ],
)
def test_master_ladder(monkeypatch, nvenc, o, expected) -> None:
    from app.stream import _variants_for

    monkeypatch.setattr(settings, "nvenc_enabled", nvenc)
    mf = SimpleNamespace(height=1080)
    assert _labels(_variants_for(mf, o)) == expected


def test_explicit_source_height_pick_is_kept_on_cpu() -> None:
    common = dict(audio_track_index=None, subtitle=None, source_height=1080, streams=None)
    assert resolve_track_opts(quality="1080p", keep_source_height=True, **common).max_height == 1080
    # NVENC servers keep the old meaning: a ceiling at the source height is a no-op.
    assert resolve_track_opts(quality="1080p", **common).max_height is None
    assert resolve_track_opts(quality="720p", **common).max_height == 720
