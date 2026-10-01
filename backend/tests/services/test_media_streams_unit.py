"""Unit tests for ffprobe stream parsing + image-subtitle classification."""
from __future__ import annotations

from app.services import media_streams


_PROBE = {
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264"},
        {
            "index": 1, "codec_type": "audio", "codec_name": "aac",
            "channels": 6, "tags": {"language": "eng", "title": "Surround"},
            "disposition": {"default": 1},
        },
        {
            "index": 2, "codec_type": "audio", "codec_name": "ac3",
            "channels": 2, "tags": {"language": "spa"},
            "disposition": {"default": 0},
        },
        {
            "index": 3, "codec_type": "subtitle", "codec_name": "subrip",
            "tags": {"language": "eng", "title": "English"},
            "disposition": {"forced": 0, "default": 1},
        },
        {
            "index": 4, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
            "tags": {"language": "eng"},
            "disposition": {"forced": 1, "default": 0},
        },
    ]
}


def test_parse_streams_audio():
    out = media_streams.parse_streams(_PROBE)
    assert len(out["audio"]) == 2
    a0 = out["audio"][0]
    assert a0 == {
        "index": 1, "codec": "aac", "language": "eng",
        "channels": 6, "title": "Surround", "default": True,
    }
    assert out["audio"][1]["default"] is False


def test_parse_streams_subtitles():
    out = media_streams.parse_streams(_PROBE)
    assert len(out["subtitles"]) == 2
    s_text = out["subtitles"][0]
    assert s_text == {
        "index": 3, "codec": "subrip", "language": "eng",
        "title": "English", "forced": False, "default": True,
    }
    s_img = out["subtitles"][1]
    assert s_img["index"] == 4
    assert s_img["forced"] is True


def test_parse_streams_empty():
    out = media_streams.parse_streams({})
    assert out == {"subtitles": [], "audio": []}


def test_is_image_subtitle():
    assert media_streams.is_image_subtitle("hdmv_pgs_subtitle") is True
    assert media_streams.is_image_subtitle("dvd_subtitle") is True
    assert media_streams.is_image_subtitle("subrip") is False
    assert media_streams.is_image_subtitle(None) is False
    assert media_streams.is_image_subtitle("SUBRIP") is False
