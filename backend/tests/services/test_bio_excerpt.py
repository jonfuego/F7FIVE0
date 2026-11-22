"""The Home hero's artist bio excerpt: the first few whole sentences (at most
four), at most about 480 characters, always cut at a sentence end unless the
first sentence alone is too long."""
from __future__ import annotations

from app.services.bio_excerpt import DEFAULT_LIMIT, MAX_SENTENCES, bio_excerpt

RADIOHEAD = (
    "Radiohead are an English rock band formed in Abingdon, Oxfordshire, in "
    "1985. The members are Thom Yorke, brothers Jonny Greenwood and Colin "
    "Greenwood, Ed O'Brien and Philip Selway. They have worked with the "
    "producer Nigel Godrich since 1994."
)

# Shaped like the bio Jon saw cut off on the Home hero (review item 21): the
# old 220-character limit stopped at "...and drummer Mick...".
RED_LORRY = (
    "Red Lorry Yellow Lorry are an English post-punk band formed in Leeds in "
    "1981. The original line-up was singer and guitarist Chris Reed, guitarist "
    "Martin Fagan, bassist Steve Smith and drummer Mick Brown. They released "
    "their first single, Beating My Head, on Red Rhino Records in 1982. Their "
    "debut album Talk About the Weather followed in 1985 and reached the UK "
    "indie chart. The band split in 1991 and Reed revived the name in 2003."
)


def test_nothing_in_nothing_out():
    assert bio_excerpt(None) is None
    assert bio_excerpt("") is None
    assert bio_excerpt("   \n  ") is None


def test_short_bio_is_kept_whole():
    assert bio_excerpt("A short band.") == "A short band."
    assert bio_excerpt("No full stop here") == "No full stop here"


def test_a_three_sentence_bio_is_kept_whole():
    assert bio_excerpt(RADIOHEAD) == RADIOHEAD


def test_long_bio_is_longer_than_before_and_ends_on_a_whole_sentence():
    out = bio_excerpt(RED_LORRY)
    assert out is not None
    # Past the old 220-character cut, and no ellipsis: whole sentences only.
    assert len(out) > 220
    assert len(out) <= DEFAULT_LIMIT
    assert "\u2026" not in out
    assert out.endswith("Talk About the Weather followed in 1985 and reached the UK indie chart.")
    assert "drummer Mick Brown." in out
    assert "split in 1991" not in out


def test_at_most_max_sentences():
    text = "One band. Two members. Three albums. Four tours. Five singles."
    assert MAX_SENTENCES == 4
    assert bio_excerpt(text) == "One band. Two members. Three albums. Four tours."


def test_a_sentence_that_would_pass_the_limit_is_dropped_whole():
    first = "The Birthday Party were an Australian post-punk band, active from 1977 to 1983."
    text = first + " " + ("Long words follow " * 40).strip() + "."
    assert bio_excerpt(text) == first


def test_never_longer_than_the_limit():
    for limit in (60, 120, 220, DEFAULT_LIMIT):
        for text in (RADIOHEAD, RED_LORRY):
            out = bio_excerpt(text, limit=limit)
            assert out is not None and len(out) <= limit


def test_a_first_sentence_over_the_limit_is_cut_at_a_word_with_an_ellipsis():
    text = "word " * 200 + "end."
    out = bio_excerpt(text)
    assert out is not None and out.endswith("\u2026")
    assert len(out) <= DEFAULT_LIMIT
    assert not out[:-1].endswith(" ")
    assert out[:-1].split(" ")[-1] == "word"


def test_abbreviations_and_initials_do_not_end_a_sentence():
    text = "Dr. Dre and J. Cole made a record with Mt. Kimbie. It was good. It sold well."
    assert bio_excerpt(text, limit=70) == "Dr. Dre and J. Cole made a record with Mt. Kimbie. It was good."
    assert bio_excerpt(text) == text
    assert bio_excerpt("Formed in the U.S. in 1980, the band toured. They split.") == (
        "Formed in the U.S. in 1980, the band toured. They split."
    )


def test_only_the_first_paragraph_and_whitespace_is_collapsed():
    text = "First   line\nwraps here.\n\nSecond paragraph is ignored."
    assert bio_excerpt(text) == "First line wraps here."


def test_question_marks_and_quotes():
    text = 'Who are they? "A band," said someone. More text follows.'
    assert bio_excerpt(text, limit=40) == 'Who are they? "A band," said someone.'
    assert bio_excerpt(text) == text
