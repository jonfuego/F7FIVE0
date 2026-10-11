"""Artist art search (batch 7 item 2): the TheAudioDB fix and the keyless
Deezer source. All HTTP is mocked; the response shapes below were taken from
the real services (TheAudioDB v1 `search.php` / `artist-mb.php`, Deezer
`search/artist`).
"""
from __future__ import annotations

import httpx
import pytest

from app.config import Settings, settings
from app.models.music import Artist, MusicVideo, MusicVideoRelease
from app.services import art_search
from app.services.art_sources import names


COLDPLAY_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"


def _audiodb_coldplay() -> dict:
    """The fields of a real TheAudioDB artist record that matter for art."""
    return {"artists": [{
        "idArtist": "111239",
        "strArtist": "Coldplay",
        "strMusicBrainzID": COLDPLAY_MBID,
        "strArtistThumb": "https://r2.theaudiodb.com/images/media/artist/thumb/uxrqxy1347913147.jpg",
        "strArtistLogo": "https://r2.theaudiodb.com/images/media/artist/logo/q094e21667518717.png",
        "strArtistCutout": "https://r2.theaudiodb.com/images/media/artist/cutout/ggq5ap1641422844.png",
        "strArtistClearart": "https://r2.theaudiodb.com/images/media/artist/clearart/ruyuwv1510827568.png",
        "strArtistWideThumb": "https://r2.theaudiodb.com/images/media/artist/widethumb/sxqspt1516190718.jpg",
        "strArtistFanart": "https://r2.theaudiodb.com/images/media/artist/fanart/spvryu1347980801.jpg",
        "strArtistFanart2": "https://r2.theaudiodb.com/images/media/artist/fanart/uupyxx1342640221.jpg",
        "strArtistFanart3": "https://r2.theaudiodb.com/images/media/artist/fanart/qstpsp1342640238.jpg",
        "strArtistFanart4": "https://r2.theaudiodb.com/images/media/artist/fanart/muf6tu1612946535.jpg",
        "strArtistBanner": "https://r2.theaudiodb.com/images/media/artist/banner/xuypqw1386331010.jpg",
    }]}


def _deezer_hit(id_, name, fans, hash_="b18856da7850c8b8cb10476fefc15657"):
    base = f"https://cdn-images.dzcdn.net/images/artist/{hash_}"
    return {
        "id": id_, "name": name, "nb_fan": fans, "type": "artist",
        "picture": f"https://api.deezer.com/artist/{id_}/image",
        "picture_small": f"{base}/56x56-000000-80-0-0.jpg",
        "picture_medium": f"{base}/250x250-000000-80-0-0.jpg",
        "picture_big": f"{base}/500x500-000000-80-0-0.jpg",
        "picture_xl": f"{base}/1000x1000-000000-80-0-0.jpg",
    }


class FakeWeb:
    """Routes the mocked HTTP for TheAudioDB and Deezer and records calls."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.audiodb = lambda request: httpx.Response(200, json={"artists": None})
        self.deezer = lambda request: httpx.Response(200, json={"data": []})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host = request.url.host
        if host == "www.theaudiodb.com":
            return self.audiodb(request)
        if host == "api.deezer.com":
            return self.deezer(request)
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    def hosts(self) -> list[str]:
        return [c.url.host for c in self.calls]


@pytest.fixture()
def web(monkeypatch):
    fake = FakeWeb()
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    # Lidarr is not connected in any of these.
    monkeypatch.setattr(settings, "lidarr_api_key", "")
    return fake


def _audiodb_server(key_ok: str = "123"):
    """TheAudioDB as it behaves today: the retired key 2 gets HTTP 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.split("/")  # /api/v1/json/<key>/<endpoint>
        key, endpoint = parts[4], parts[5]
        if key != key_ok:
            return httpx.Response(404, json={"Message": "Not found"})
        if endpoint == "artist-mb.php":
            if request.url.params.get("i") == COLDPLAY_MBID:
                return httpx.Response(200, json=_audiodb_coldplay())
            return httpx.Response(200, json={"artists": None})
        if endpoint == "search.php":
            if request.url.params.get("s", "").casefold() == "coldplay":
                return httpx.Response(200, json=_audiodb_coldplay())
            return httpx.Response(200, json={"artists": None})
        return httpx.Response(404, json={"Message": "Not found"})
    return handler


def _artist(db, name="Coldplay", mbid=None):
    a = Artist(name=name, mbid=mbid)
    db.add(a)
    db.flush()
    return a


# ---------------------------------------------------------------------------
# TheAudioDB fix
# ---------------------------------------------------------------------------
def test_default_audiodb_key_is_the_current_free_key():
    # The old public test key "2" is retired and answers HTTP 404.
    assert Settings.model_fields["audiodb_api_key"].default == "123"


def test_audiodb_candidates_with_real_response_shape(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "audiodb_api_key", "123")
    web.audiodb = _audiodb_server()
    artist = _artist(db_session)  # no MusicBrainz id: found by name

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    audiodb = [c for c in candidates if c["source"] == "audiodb"]
    labels = {c["label"] for c in audiodb}
    assert {
        "AudioDB thumb", "AudioDB fanart", "AudioDB banner",
        "AudioDB wide thumb", "AudioDB logo",
    } <= labels
    thumb = next(c for c in audiodb if c["label"] == "AudioDB thumb")
    assert thumb["url"].endswith("/thumb/uxrqxy1347913147.jpg")
    assert thumb["preview_url"] == thumb["url"] + "/small"
    # No "did not answer" note: the source worked.
    assert not any("TheAudioDB" in n for n in notes)
    sent = [c for c in web.calls if c.url.host == "www.theaudiodb.com"]
    assert sent[0].url.path == "/api/v1/json/123/search.php"


def test_audiodb_looks_up_by_musicbrainz_id_when_known(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "audiodb_api_key", "123")
    web.audiodb = _audiodb_server()
    # The library spells the name differently; the MBID still finds the artist.
    artist = _artist(db_session, name="Cold Play", mbid=COLDPLAY_MBID)

    candidates, _notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert any(c["source"] == "audiodb" for c in candidates)
    sent = [c for c in web.calls if c.url.host == "www.theaudiodb.com"]
    assert sent[0].url.path == "/api/v1/json/123/artist-mb.php"
    assert sent[0].url.params["i"] == COLDPLAY_MBID


@pytest.mark.parametrize("old_key", ["2", "1"])
def test_retired_key_in_env_is_upgraded(db_session, web, monkeypatch, old_key):
    # Installs copied `AUDIODB_API_KEY=2` from the old .env.example.
    monkeypatch.setattr(settings, "audiodb_api_key", old_key)
    web.audiodb = _audiodb_server()
    artist = _artist(db_session)

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert any(c["source"] == "audiodb" for c in candidates)
    assert not any("TheAudioDB" in n for n in notes)
    sent = [c for c in web.calls if c.url.host == "www.theaudiodb.com"]
    assert all("/json/123/" in c.url.path for c in sent)


def test_audiodb_http_error_is_a_note_not_silence(db_session, web, monkeypatch):
    # A custom key TheAudioDB rejects: before the fix this returned [] with no
    # note, so the modal showed nothing at all.
    monkeypatch.setattr(settings, "audiodb_api_key", "badkey")
    web.audiodb = _audiodb_server()
    artist = _artist(db_session)

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert candidates == []
    assert "TheAudioDB did not answer." in notes


def test_audiodb_artist_not_found_is_not_an_error(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "audiodb_api_key", "123")
    web.audiodb = _audiodb_server()
    artist = _artist(db_session, name="Edward Ka-Spel")

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert candidates == []
    assert not any("TheAudioDB" in n for n in notes)


# ---------------------------------------------------------------------------
# Deezer: the keyless artist source
# ---------------------------------------------------------------------------
def _deezer_new_order(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/search/artist"
    assert request.url.params["q"] == "New Order"
    return httpx.Response(200, json={"data": [
        _deezer_hit(11916995, "New Order", 94, hash_="aaaa"),
        _deezer_hit(2016, "New Order", 949497, hash_="bbbb"),
        _deezer_hit(11416926, "New Beat Order", 2598, hash_="cccc"),
        _deezer_hit(171567, "The New Order", 195, hash_="dddd"),
        # A same-name artist with no photo: Deezer's empty-hash placeholder.
        _deezer_hit(7, "New Order", 5, hash_=""),
    ]})


def test_artist_candidates_from_deezer_without_lidarr(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "deezer_enabled", True)
    monkeypatch.setattr(settings, "audiodb_api_key", "")  # AudioDB off too
    web.deezer = _deezer_new_order
    artist = _artist(db_session, name="New Order")

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert [c["source"] for c in candidates] == ["deezer", "deezer"]
    # Most followed same-name artist first. The empty-picture stub, "New Beat
    # Order" and "The New Order" are not offered.
    first = candidates[0]
    assert first["url"] == (
        "https://cdn-images.dzcdn.net/images/artist/bbbb/1000x1000-000000-80-0-0.jpg"
    )
    assert first["preview_url"].endswith("/250x250-000000-80-0-0.jpg")
    assert first["ref"] == first["url"]
    assert first["label"] == "Deezer artist photo"
    assert "New Beat Order" not in str(candidates)
    # Lidarr is not connected: the soft callout stays, the search still answers.
    assert any("Lidarr" in n for n in notes)
    assert web.hosts() == ["api.deezer.com"]


def test_leading_the_is_ignored_only_when_nothing_else_matches(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "deezer_enabled", True)
    web.deezer = lambda request: httpx.Response(200, json={"data": [
        _deezer_hit(9025, "Birthday Party", 9952, hash_="eeee"),
    ]})
    artist = _artist(db_session, name="The Birthday Party")

    candidates, _notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert [c["source"] for c in candidates] == ["deezer"]


def test_music_video_artist_gets_deezer_candidates(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "deezer_enabled", True)
    monkeypatch.setattr(settings, "itunes_enabled", False)
    web.deezer = lambda request: httpx.Response(200, json={"data": [
        _deezer_hit(545, "Depeche Mode", 3282761),
        _deezer_hit(217460745, "Depeche Mode & ANNA", 75),
    ]})
    artist = _artist(db_session, name="Depeche Mode")
    release = MusicVideoRelease(
        artist_id=artist.id, title="Strange", source_subpath="Strange",
    )
    db_session.add(release)
    db_session.flush()
    mv = MusicVideo(artist_id=artist.id, release_id=release.id, title="Enjoy the Silence")
    db_session.add(mv)
    db_session.flush()

    candidates, _notes = art_search.search_candidates_with_notes(
        db_session, kind="music_video", entity_id=mv.id,
    )

    assert [c["source"] for c in candidates] == ["deezer"]
    assert "/545/" not in candidates[0]["url"]  # it is the CDN picture URL
    assert candidates[0]["url"].startswith("https://cdn-images.dzcdn.net/")


def test_deezer_quota_error_becomes_a_note(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "deezer_enabled", True)
    # Deezer reports a quota problem with HTTP 200 and an error object.
    web.deezer = lambda request: httpx.Response(200, json={"error": {
        "type": "Exception", "message": "Quota limit exceeded", "code": 4,
    }})
    artist = _artist(db_session, name="Modest Mouse")

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert candidates == []
    assert "Deezer did not answer." in notes


def test_deezer_off_is_not_asked(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "deezer_enabled", False)
    artist = _artist(db_session, name="Modest Mouse")

    art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert "api.deezer.com" not in web.hosts()


def test_deezer_apply_path_rederives_the_picked_candidate(db_session, web, monkeypatch):
    """`/from-search` re-runs the search and matches on (source, ref)."""
    monkeypatch.setattr(settings, "deezer_enabled", True)
    web.deezer = _deezer_new_order
    artist = _artist(db_session, name="New Order")
    picked = art_search.search_candidates(
        db_session, kind="artist", entity_id=artist.id,
    )[0]

    again = art_search.search_candidates(
        db_session, kind="artist", entity_id=artist.id,
    )

    assert any(
        c["source"] == picked["source"] and c["ref"] == picked["ref"] for c in again
    )


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a,b", [
    ("Edward KaSpel", "Edward Ka-Spel"),
    ("The Birthday Party", "Birthday Party"),
    ("Beyoncé", "Beyonce"),
    ("Simon & Garfunkel", "Simon and Garfunkel"),
    ("AC/DC", "ACDC"),
    ("  New   Order ", "new order"),
])
def test_same_artist_folds_small_differences(a, b):
    assert names.same_artist(a, b)


@pytest.mark.parametrize("a,b", [
    ("New Order", "New Beat Order"),
    ("Modest Mouse", "Karaoke - Modest Mouse"),
    ("Jeremiah Green of Modest Mouse", "Modest Mouse"),
    ("Depeche Mode", "Depeche Mode & ANNA"),
    ("", ""),
    ("!!!", "???"),
])
def test_same_artist_rejects_different_artists(a, b):
    assert not names.same_artist(a, b)


def test_the_the_keeps_a_name():
    assert names.match_key("The The") == "the"
    assert names.same_artist("The The", "The The")
