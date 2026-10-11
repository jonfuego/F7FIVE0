"""The Home hero's artist bio excerpt: one or two sentences, at most about
220 characters, cut at a sentence end where possible."""
from __future__ import annotations

from app.services.bio_excerpt import DEFAULT_LIMIT, bio_excerpt

RADIOHEAD = (
    "Radiohead are an English rock band formed in Abingdon, Oxfordshire, in "
    "1985. The members are Thom Yorke, brothers Jonny Greenwood and Colin "
    "Greenwood, Ed O'Brien and Philip Selway. They have worked with the "
    "producer Nigel Godrich since 1994."
)


def test_nothing_in_nothing_out():
    assert bio_excerpt(None) is None
    assert bio_excerpt("") is None
    assert bio_excerpt("   \n  ") is None


def test_short_bio_is_kept_whole():
    assert bio_excerpt("A short band.") == "A short band."
    assert bio_excerpt("No full stop here") == "No full stop here"


def test_two_sentences_at_most_and_cut_at_a_sentence_end():
    out = bio_excerpt(RADIOHEAD)
    assert out is not None and out.endswith("Philip Selway.")
    assert len(out) <= DEFAULT_LIMIT
    assert out.endswith(".")
    assert "Godrich" not in out


def test_two_short_sentences_are_both_kept():
    text = "One band. Two members. Three albums."
    assert bio_excerpt(text) == "One band. Two members."


def test_second_sentence_dropped_when_it_would_pass_the_limit():
    first = "The Birthday Party were an Australian post-punk band, active from 1977 to 1983."
    text = first + " " + ("Long words follow " * 12).strip() + "."
    assert bio_excerpt(text) == first


def test_never_longer_than_the_limit():
    for limit in (60, 120, DEFAULT_LIMIT):
        out = bio_excerpt(RADIOHEAD, limit=limit)
        assert out is not None and len(out) <= limit


def test_a_first_sentence_over_the_limit_is_cut_at_a_word_with_an_ellipsis():
    text = "word " * 100 + "end."
    out = bio_excerpt(text)
    assert out is not None and out.endswith("\u2026")
    assert len(out) <= DEFAULT_LIMIT
    assert not out[:-1].endswith(" ")
    assert out[:-1].split(" ")[-1] == "word"


def test_abbreviations_and_initials_do_not_end_a_sentence():
    text = "Dr. Dre and J. Cole made a record with Mt. Kimbie. It was good. It sold well."
    assert bio_excerpt(text) == "Dr. Dre and J. Cole made a record with Mt. Kimbie. It was good."
    assert bio_excerpt("Formed in the U.S. in 1980, the band toured. They split.") == (
        "Formed in the U.S. in 1980, the band toured. They split."
    )


def test_only_the_first_paragraph_and_whitespace_is_collapsed():
    text = "First   line\nwraps here.\n\nSecond paragraph is ignored."
    assert bio_excerpt(text) == "First line wraps here."


def test_question_marks_and_quotes():
    text = 'Who are they? "A band," said someone. More text follows.'
    assert bio_excerpt(text) == 'Who are they? "A band," said someone.'
