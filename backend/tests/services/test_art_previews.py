"""Art picker previews (batch 7 item 4).

Each candidate carries a small `preview_url` for the modal's tile while
`url` stays the full-size image that applying downloads. All HTTP is mocked.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx

from app.config import settings
from app.models.movie import Movie
from app.services import art_search, tmdb_key
from app.services.art_sources import audiodb as audiodb_source
from app.services.art_sources import coverart as coverart_source
from app.services.art_sources import itunes as itunes_source
from app.services.art_sources import previews
from app.services.art_sources import tmdb as tmdb_source


def _mock_client(module: Any, monkeypatch, handler: Callable[[httpx.Request], httpx.Response]):
    """Make `module.httpx.Client(...)` talk to `handler` instead of the network."""
    real = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "Client", factory)


def _tmdb_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/3/movie/603/images"
    return httpx.Response(200, json={
        "posters": [{"file_path": "/poster.jpg", "iso_639_1": "en"}],
        "backdrops": [{"file_path": "/backdrop.jpg", "iso_639_1": None}],
    })


def test_tmdb_candidates_preview_small_and_apply_original(monkeypatch):
    _mock_client(tmdb_source, monkeypatch, _tmdb_handler)

    items = tmdb_source.movie_images("testkey", 603)
    by_ref = {i["ref"]: i for i in items}

    poster = by_ref["/poster.jpg"]
    assert poster["url"] == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert poster["preview_url"] == "https://image.tmdb.org/t/p/w342/poster.jpg"

    backdrop = by_ref["/backdrop.jpg"]
    assert backdrop["url"] == "https://image.tmdb.org/t/p/original/backdrop.jpg"
    assert backdrop["preview_url"] == "https://image.tmdb.org/t/p/w300/backdrop.jpg"

    # Every preview is a TMDB size no bigger than w342; none is `original`.
    for item in items:
        size = item["preview_url"].split("/t/p/")[1].split("/")[0]
        assert size != "original"
        assert int(size.lstrip("w")) <= 342


def test_tmdb_apply_path_still_uses_original(db_session, monkeypatch):
    """The aggregator keeps `url` at original and the apply endpoint matches
    on (source, ref) and downloads `url`, never the preview."""
    _mock_client(tmdb_source, monkeypatch, _tmdb_handler)
    monkeypatch.setattr(settings, "radarr_api_key", "")
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")

    movie = Movie(title="The Matrix", year=1999, tmdb_id=603)
    db_session.add(movie)
    db_session.flush()

    candidates = art_search.search_candidates(
        db_session, kind="movie", entity_id=movie.id,
    )
    poster = next(c for c in candidates if c["ref"] == "/poster.jpg")
    assert "/t/p/original/" in poster["url"]
    assert "/t/p/w342/" in poster["preview_url"]


def test_itunes_preview_is_resized_and_url_is_large(monkeypatch):
    art = "https://is1-ssl.mzstatic.com/image/thumb/Music/abc/100x100bb.jpg"
    items = itunes_source._normalize_albums(
        [{"artworkUrl100": art, "collectionName": "Album"}],
        expected_artist="X",
    )
    assert items[0]["url"].endswith("/1000x1000bb.jpg")
    assert items[0]["preview_url"].endswith("/300x300bb.jpg")
    assert items[0]["preview_url"].startswith("https://is1-ssl.mzstatic.com/")


def test_audiodb_preview_variant(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"artists": [{
            "strArtist": "Bauhaus",
            "strArtistThumb": "https://r2.theaudiodb.com/images/media/artist/thumb/x.jpg",
            "strArtistLogo": "https://example.com/not-audiodb/logo.png",
        }]})

    _mock_client(audiodb_source, monkeypatch, handler)
    items = audiodb_source.search_artist("2", "Bauhaus")
    by_label = {i["label"]: i for i in items}

    thumb = by_label["AudioDB thumb"]
    assert thumb["url"] == "https://r2.theaudiodb.com/images/media/artist/thumb/x.jpg"
    assert thumb["preview_url"] == thumb["url"] + "/small"
    # A host with no known size scheme keeps the full URL as its preview.
    logo = by_label["AudioDB logo"]
    assert logo["preview_url"] == logo["url"]


def test_coverart_preview_is_thumbnail_and_apply_stays_under_cap(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"images": [{
            "front": True,
            "image": "https://coverartarchive.org/release/r/1.jpg",
            "thumbnails": {
                "250": "https://coverartarchive.org/release/r/1-250.jpg",
                "500": "https://coverartarchive.org/release/r/1-500.jpg",
                "1200": "https://coverartarchive.org/release/r/1-1200.jpg",
            },
        }]})

    _mock_client(coverart_source, monkeypatch, handler)
    items = coverart_source.release_group_images("11111111-1111-1111-1111-111111111111")
    assert items[0]["preview_url"].endswith("1-250.jpg")
    assert items[0]["url"].endswith("1-1200.jpg")


def test_arr_tmdb_urls_get_a_preview_and_unknown_hosts_do_not(monkeypatch):
    items = art_search._normalize_images("radarr", "Radarr", [
        {"coverType": "poster", "remoteUrl": "https://image.tmdb.org/t/p/original/p.jpg"},
        {"coverType": "fanart", "remoteUrl": "https://image.tmdb.org/t/p/original/f.jpg"},
        {"coverType": "poster", "remoteUrl": "https://other.example/p.jpg"},
    ])
    assert items[0]["preview_url"] == "https://image.tmdb.org/t/p/w342/p.jpg"
    assert items[1]["preview_url"] == "https://image.tmdb.org/t/p/w300/f.jpg"
    assert items[2]["preview_url"] == "https://other.example/p.jpg"


def test_aggregator_fills_missing_preview_with_url(db_session, monkeypatch):
    """A source that returns no `preview_url` still yields one (the full URL),
    so clients can always read the field."""
    monkeypatch.setattr(settings, "radarr_api_key", "")
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")
    monkeypatch.setattr(
        tmdb_source, "movie_images",
        lambda key, tmdb_id: [
            {"source": "tmdb", "ref": "/p.jpg", "url": "https://x/p.jpg", "label": "TMDB poster"},
        ],
    )
    movie = Movie(title="Heat", year=1995, tmdb_id=949)
    db_session.add(movie)
    db_session.flush()

    candidates = art_search.search_candidates(
        db_session, kind="movie", entity_id=movie.id,
    )
    assert candidates[0]["preview_url"] == "https://x/p.jpg"


def test_preview_helpers_leave_unknown_urls_alone():
    assert previews.itunes_url("https://x/y.jpg", "300x300bb") == "https://x/y.jpg"
    assert previews.audiodb_url("https://example.com/a.jpg", "small") == "https://example.com/a.jpg"
    assert previews.preview_for("https://example.com/a.jpg") is None


def test_search_endpoint_returns_preview_url_alongside_url(client, db_session, monkeypatch):
    """GET /api/admin/art/search keeps `url` (full size) and adds `preview_url`."""
    _mock_client(tmdb_source, monkeypatch, _tmdb_handler)
    monkeypatch.setattr(settings, "radarr_api_key", "")
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")

    movie = Movie(title="The Matrix", year=1999, tmdb_id=603)
    db_session.add(movie)
    db_session.flush()

    r = client.get("/api/admin/art/search", params={"kind": "movie", "id": str(movie.id)})
    assert r.status_code == 200, r.text
    poster = next(c for c in r.json()["candidates"] if c["ref"] == "/poster.jpg")
    assert poster["url"] == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert poster["preview_url"] == "https://image.tmdb.org/t/p/w342/poster.jpg"
