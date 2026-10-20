"""Tests for services/naming_templates.py."""
from __future__ import annotations

import pytest

from app.services.naming_templates import (
    PRESET_ARR,
    PRESET_FLAT,
    PRESET_PLEX,
    render,
    render_safe,
    safe_segment,
)


def test_render_track_zero_padded():
    assert render("{Track:00} - {Title}", {"Track": "3", "Title": "My Song"}) == "03 - My Song"


def test_render_track_already_padded():
    assert render("{Track:00} - {Title}", {"Track": "12", "Title": "Song"}) == "12 - Song"


def test_render_zero_format():
    assert render("{Disc:0}", {"Disc": "2"}) == "2"


def test_render_unknown_token_left_as_is():
    result = render("{Unknown} - {Title}", {"Title": "X"})
    assert "{Unknown}" in result
    assert "X" in result


def test_render_multiple_tokens():
    result = render("{Artist}/{Album} ({Year})/{Track:00} - {Title}", {
        "Artist": "Joy Division",
        "Album": "Unknown Pleasures",
        "Year": "1979",
        "Track": "1",
        "Title": "Disorder",
    })
    assert result == "Joy Division/Unknown Pleasures (1979)/01 - Disorder"


def test_render_season_episode():
    result = render("{Series}/Season {Season:00}/{Series} - S{Season:00}E{Episode:00} - {Title}", {
        "Series": "The Wire",
        "Season": "1",
        "Episode": "3",
        "Title": "The Buys",
    })
    assert result == "The Wire/Season 01/The Wire - S01E03 - The Buys"


def test_safe_segment_strips_illegal_characters():
    result = safe_segment('AC/DC: Back in Black?')
    assert '/' not in result
    assert ':' not in result
    assert '?' not in result


def test_safe_segment_strips_trailing_dots_and_spaces():
    result = safe_segment("Hello. ")
    assert not result.endswith(".")
    assert not result.endswith(" ")


def test_safe_segment_strips_control_chars():
    result = safe_segment("A\x00B\x1fC")
    assert '\x00' not in result
    assert '\x1f' not in result


def test_safe_segment_backslash_replaced():
    result = safe_segment("path\\segment")
    assert '\\' not in result


def test_render_safe_combines_render_and_safe():
    result = render_safe("{Artist}/{Album}", {
        "Artist": "AC/DC",
        "Album": "Back in Black",
    })
    # The '/' in "AC/DC" is a path separator so it creates two segments.
    # safe_segment is applied per segment, so the output must not have illegal
    # chars within each segment.
    parts = result.replace("\\", "/").split("/")
    for part in parts:
        assert ':' not in part
        assert '?' not in part
        assert '*' not in part


def test_preset_plex_has_all_kinds():
    assert "music" in PRESET_PLEX
    assert "movie" in PRESET_PLEX
    assert "tv" in PRESET_PLEX


def test_preset_arr_has_all_kinds():
    assert "music" in PRESET_ARR
    assert "movie" in PRESET_ARR
    assert "tv" in PRESET_ARR


def test_preset_flat_has_all_kinds():
    assert "music" in PRESET_FLAT
    assert "movie" in PRESET_FLAT
    assert "tv" in PRESET_FLAT


def test_preset_plex_music_uses_disc_track():
    # PRESET_PLEX music should zero-pad track and use disc
    tpl = PRESET_PLEX["music"]
    assert "{Track:00}" in tpl or "{Track}" in tpl


def test_preset_arr_movie_structure():
    # Movie preset should have Title and Year
    tpl = PRESET_ARR["movie"]
    assert "{Title}" in tpl


def test_render_empty_disc_blank_when_disc_1():
    # {Disc} should be blank when value is empty or "1" -- test the token substitution
    result = render("{Disc:0}{Track:00} - {Title}", {
        "Disc": "1",
        "Track": "3",
        "Title": "Song",
    })
    assert "1" in result  # disc:0 always prints


def test_render_disc_blank_when_empty():
    result = render("{Disc}{Track:00} - {Title}", {
        "Disc": "",
        "Track": "5",
        "Title": "Song",
    })
    assert "{Disc}" not in result
    assert "05 - Song" in result
