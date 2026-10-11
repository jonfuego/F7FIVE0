"""Artist bios through Wikidata.

MusicBrainz links most artists to Wikidata, not straight to Wikipedia, and
enrichment only followed a Wikipedia link, so most artists had no bio. These
cover the bio lookup, the backfill and enrichment. All HTTP is mocked.
"""
from __future__ import annotations

from app.models.music import Artist
from app.services.metadata import runner
from app.services.metadata._base import ProviderError

WIKIDATA = "https://www.wikidata.org/wiki/Q44190"


class _FakeWikidata:
    titles: dict[str, str | None] = {}
    calls: list[str] = []
    fail = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def enwiki_title(self, value):
        _FakeWikidata.calls.append(value)
        if _FakeWikidata.fail:
            raise ProviderError("down")
        return _FakeWikidata.titles.get(value)


class _FakeWikipedia:
    extracts: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_extract(self, title):
        text = _FakeWikipedia.extracts.get(title)
        return {"extract": text} if text else None


def _fakes(monkeypatch):
    from app.services.metadata import wikidata
    _FakeWikidata.titles, _FakeWikidata.calls, _FakeWikidata.fail = {}, [], False
    _FakeWikipedia.extracts = {}
    monkeypatch.setattr(wikidata, "WikidataClient", _FakeWikidata)
    monkeypatch.setattr(runner, "WikipediaClient", _FakeWikipedia)


def _artist(db, name, links):
    a = Artist(name=name, links=links)
    db.add(a)
    db.commit()
    return a


def test_bio_through_wikidata(monkeypatch):
    _fakes(monkeypatch)
    _FakeWikidata.titles[WIKIDATA] = "Radiohead"
    _FakeWikipedia.extracts["Radiohead"] = "Radiohead are an English rock band."

    assert runner.wikipedia_bio(None, WIKIDATA) == ("Radiohead are an English rock band.", True)
    assert runner.wikipedia_bio(None, None) == (None, False)


def test_backfill_fills_remembers_misses_and_reruns_clean(db_session, monkeypatch):
    _fakes(monkeypatch)
    _FakeWikidata.titles[WIKIDATA] = "Radiohead"
    _FakeWikipedia.extracts["Radiohead"] = "Radiohead are an English rock band."
    hit = _artist(db_session, "Radiohead", [{"kind": "wikidata", "url": WIKIDATA}])
    miss = _artist(db_session, "Nobody", [{"kind": "wikidata", "url": "https://www.wikidata.org/wiki/Q1"}])
    nolink = _artist(db_session, "No Links", [])

    assert runner.backfill_artist_bios(db_session) == 1
    for a in (hit, miss, nolink):
        db_session.refresh(a)
    assert hit.bio_text.startswith("Radiohead") and hit.bio_source == "wikipedia"
    assert miss.bio_text is None and miss.bio_source == runner.BIO_NOT_FOUND
    assert nolink.bio_source is None

    asked = len(_FakeWikidata.calls)
    assert runner.backfill_artist_bios(db_session) == 0
    assert len(_FakeWikidata.calls) == asked


def test_backfill_service_error_is_not_remembered(db_session, monkeypatch):
    _fakes(monkeypatch)
    _FakeWikidata.fail = True
    a = _artist(db_session, "Radiohead", [{"kind": "wikidata", "url": WIKIDATA}])

    assert runner.backfill_artist_bios(db_session) == 0
    db_session.refresh(a)
    assert a.bio_source is None


def test_backfill_walks_in_batches_and_stops_after_repeated_errors(db_session, monkeypatch):
    _fakes(monkeypatch)
    _FakeWikidata.fail = True
    artists = [
        _artist(db_session, f"A{i}", [{"kind": "wikidata", "url": f"https://www.wikidata.org/wiki/Q{i + 1}"}])
        for i in range(6)
    ]

    assert runner.backfill_artist_bios(db_session, batch_size=2, max_failures=3) == 0
    assert len(_FakeWikidata.calls) == 3  # gave up after three errors in a row
    for a in artists:
        db_session.refresh(a)
        assert a.bio_source is None  # nothing remembered, so a later run asks again

    _FakeWikidata.fail = False
    for i in range(6):
        _FakeWikidata.titles[f"https://www.wikidata.org/wiki/Q{i + 1}"] = f"T{i}"
        _FakeWikipedia.extracts[f"T{i}"] = f"Text {i}."
    assert runner.backfill_artist_bios(db_session, batch_size=2) == 6


def test_backfill_uses_a_wikipedia_link_without_asking_wikidata(db_session, monkeypatch):
    _fakes(monkeypatch)
    a = _artist(db_session, "Radiohead", [
        {"kind": "wikipedia", "url": "https://en.wikipedia.org/wiki/Radiohead"},
    ])
    _FakeWikipedia.extracts["https://en.wikipedia.org/wiki/Radiohead"] = "Radiohead are an English rock band."

    assert runner.backfill_artist_bios(db_session) == 1
    db_session.refresh(a)
    assert a.bio_source == "wikipedia"
    assert _FakeWikidata.calls == []


def test_backfill_pauses_between_artists(db_session, monkeypatch):
    _fakes(monkeypatch)
    sleeps = []
    monkeypatch.setattr(runner.time, "sleep", lambda s: sleeps.append(s))
    for i in range(3):
        _FakeWikidata.titles[f"https://www.wikidata.org/wiki/Q{i + 1}"] = None
        _artist(db_session, f"A{i}", [{"kind": "wikidata", "url": f"https://www.wikidata.org/wiki/Q{i + 1}"}])

    runner.backfill_artist_bios(db_session, pause_sec=0.5)
    assert sleeps == [0.5, 0.5, 0.5]


class _FakeMusicBrainz:
    payload: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_artist(self, mbid):
        return _FakeMusicBrainz.payload


def _enrich_setup(db, monkeypatch, **artist_fields):
    _fakes(monkeypatch)
    monkeypatch.setattr(runner, "MusicBrainzClient", _FakeMusicBrainz)
    _FakeMusicBrainz.payload = {
        "relations": [{"type": "wikidata", "url": {"resource": WIKIDATA}}],
    }
    a = Artist(name="Radiohead", mbid="a74b1b7f-71a5-4011-9441-d0b5e4122711", **artist_fields)
    db.add(a)
    db.commit()
    return a


def test_enrich_follows_the_wikidata_link_and_saves_the_links(db_session, monkeypatch):
    a = _enrich_setup(db_session, monkeypatch)
    _FakeWikidata.titles[WIKIDATA] = "Radiohead"
    _FakeWikipedia.extracts["Radiohead"] = "Radiohead are an English rock band."

    assert runner.enrich_artist(db_session, a.id, force=True).status == "ok"
    db_session.refresh(a)
    assert a.bio_text.startswith("Radiohead are") and a.bio_source == "wikipedia"
    assert a.links == [{"kind": "wikidata", "url": WIKIDATA}]


def test_enrich_keeps_an_existing_bio_when_wikipedia_is_down(db_session, monkeypatch):
    a = _enrich_setup(db_session, monkeypatch, bio_text="Old bio.", bio_source="wikipedia")
    _FakeWikidata.fail = True

    runner.enrich_artist(db_session, a.id, force=True)
    db_session.refresh(a)
    assert a.bio_text == "Old bio." and a.bio_source == "wikipedia"


def test_enrich_remembers_a_link_with_no_english_article(db_session, monkeypatch):
    a = _enrich_setup(db_session, monkeypatch)

    runner.enrich_artist(db_session, a.id, force=True)
    db_session.refresh(a)
    assert a.bio_text is None and a.bio_source == runner.BIO_NOT_FOUND
