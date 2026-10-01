"""Unit tests for the LRC parser and lyrics resolution helpers (no ffmpeg)."""
from __future__ import annotations

from app.services import lyrics


_SYNCED_LRC = """[ar:Some Artist]
[ti:A Song]
[00:12.34]First line
[00:15.00]Second line
[01:02.50]Third line
"""


def test_parse_lrc_synced():
    result = lyrics.parse_lrc(_SYNCED_LRC)
    assert result.synced is True
    assert result.source == "lrc"
    assert result.lines is not None
    assert result.lines[0] == {"time_ms": 12_340, "text": "First line"}
    assert result.lines[1] == {"time_ms": 15_000, "text": "Second line"}
    assert result.lines[2] == {"time_ms": 62_500, "text": "Third line"}
    assert "First line" in (result.text or "")


def test_parse_lrc_centiseconds_vs_millis():
    two = lyrics.parse_lrc("[00:01.50]x")
    assert two.lines[0]["time_ms"] == 1_500
    three = lyrics.parse_lrc("[00:01.500]x")
    assert three.lines[0]["time_ms"] == 1_500


def test_parse_lrc_multiple_timestamps_per_line():
    result = lyrics.parse_lrc("[00:10.00][00:40.00]Chorus")
    assert result.synced is True
    times = sorted(line["time_ms"] for line in result.lines)
    assert times == [10_000, 40_000]
    assert all(line["text"] == "Chorus" for line in result.lines)


def test_parse_lrc_sorts_by_time():
    result = lyrics.parse_lrc("[00:40.00]late\n[00:10.00]early")
    assert [line["text"] for line in result.lines] == ["early", "late"]


def test_parse_lrc_plain_text_unsynced():
    result = lyrics.parse_lrc("just some\nplain lyrics")
    assert result.synced is False
    assert result.lines is None
    assert result.text == "just some\nplain lyrics"
    assert result.source == "lrc"


def test_parse_lrc_empty():
    result = lyrics.parse_lrc("")
    assert result.synced is False
    assert result.text is None
    assert result.source is None


def test_lrc_sidecar_path():
    assert lyrics.lrc_sidecar_path("/x/y/song.flac") == "/x/y/song.lrc"
    assert lyrics.lrc_sidecar_path(r"C:\m\track.mp3") == r"C:\m\track.lrc"


def test_read_lrc_sidecar_roundtrip(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"not real audio")
    (tmp_path / "song.lrc").write_text(_SYNCED_LRC, encoding="utf-8")
    result = lyrics.read_lrc_sidecar(str(media))
    assert result is not None
    assert result.synced is True
    assert result.source == "lrc"


def test_read_lrc_sidecar_absent(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    assert lyrics.read_lrc_sidecar(str(media)) is None


def test_extract_embedded_lyrics_text_case_insensitive():
    assert lyrics.extract_embedded_lyrics_text({"LYRICS": "hi"}) == "hi"
    assert lyrics.extract_embedded_lyrics_text({"lyrics": "hi"}) == "hi"
    assert lyrics.extract_embedded_lyrics_text({"UNSYNCEDLYRICS": "yo"}) == "yo"
    assert lyrics.extract_embedded_lyrics_text({"lyrics-eng": "en"}) == "en"


def test_extract_embedded_lyrics_text_none():
    assert lyrics.extract_embedded_lyrics_text({}) is None
    assert lyrics.extract_embedded_lyrics_text({"title": "x"}) is None


def test_resolve_lyrics_prefers_sidecar(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    (tmp_path / "song.lrc").write_text("[00:01.00]sidecar wins", encoding="utf-8")

    # Even if embedded exists, sidecar should win.
    monkeypatch.setattr(
        lyrics, "read_embedded_lyrics",
        lambda p: lyrics.LyricsResult(False, None, "embedded", "embedded"),
    )
    result = lyrics.resolve_lyrics(str(media))
    assert result.source == "lrc"
    assert result.synced is True


def test_resolve_lyrics_falls_back_to_embedded(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    monkeypatch.setattr(
        lyrics, "read_embedded_lyrics",
        lambda p: lyrics.LyricsResult(False, None, "embedded text", "embedded"),
    )
    result = lyrics.resolve_lyrics(str(media))
    assert result.source == "embedded"
    assert result.text == "embedded text"


def test_resolve_lyrics_empty_when_nothing(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    monkeypatch.setattr(lyrics, "read_embedded_lyrics", lambda p: None)
    result = lyrics.resolve_lyrics(str(media))
    assert result.source is None
    assert result.synced is False
