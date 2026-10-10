"""Art search beyond *arr (punch-list item 7, sources half).

art_search returns candidates from the art_sources adapters (TMDB,
TheAudioDB, iTunes, Cover Art Archive) with a per-candidate source tag,
without any *arr configured, and one failing source does not drop the
others.
"""
from __future__ import annotations

from app.config import settings
from app.models.movie import Movie
from app.models.music import Artist, MusicVideo, MusicVideoRelease
from app.services import art_search
from app.services import tmdb_key
from app.services.art_sources import audiodb as audiodb_source
from app.services.art_sources import itunes as itunes_source
from app.services.art_sources import tmdb as tmdb_source


def test_artist_art_from_sources_without_arr(db_session, monkeypatch):
    # No Lidarr key: the only sources are TheAudioDB and (for a music
    # video) iTunes. Point AudioDB at a fake result.
    monkeypatch.setattr(settings, "lidarr_api_key", "")
    monkeypatch.setattr(settings, "audiodb_api_key", "2")
    monkeypatch.setattr(
        audiodb_source, "search_artist",
        lambda key, name: [
            {
                "source": "audiodb",
                "ref": "https://cdn.example/thumb.jpg",
                "url": "https://cdn.example/thumb.jpg",
                "label": "AudioDB thumb",
            },
        ],
    )

    artist = Artist(name="Bauhaus")
    db_session.add(artist)
    db_session.flush()

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="artist", entity_id=artist.id,
    )
    assert [c["source"] for c in candidates] == ["audiodb"]
    assert candidates[0]["url"] == "https://cdn.example/thumb.jpg"
    # Lidarr not set up -> soft callout, no raw error.
    assert any("Lidarr" in n for n in notes)


def test_music_video_uses_itunes_and_audiodb(db_session, monkeypatch):
    monkeypatch.setattr(settings, "lidarr_api_key", "")
    monkeypatch.setattr(settings, "audiodb_api_key", "2")
    monkeypatch.setattr(settings, "itunes_enabled", True)
    monkeypatch.setattr(
        audiodb_source, "search_artist",
        lambda key, name: [
            {"source": "audiodb", "ref": "a", "url": "https://x/a.jpg", "label": "AudioDB thumb"},
        ],
    )
    monkeypatch.setattr(
        itunes_source, "search_artist",
        lambda name: [
            {"source": "itunes", "ref": "b", "url": "https://x/b.jpg", "label": "iTunes album"},
        ],
    )

    artist = Artist(name="A-ha")
    db_session.add(artist)
    db_session.flush()
    release = MusicVideoRelease(
        artist_id=artist.id, title="Take On Me", source_subpath="Take On Me",
    )
    db_session.add(release)
    db_session.flush()
    mv = MusicVideo(
        artist_id=artist.id, release_id=release.id, title="Take On Me",
    )
    db_session.add(mv)
    db_session.flush()

    candidates, _notes = art_search.search_candidates_with_notes(
        db_session, kind="music_video", entity_id=mv.id,
    )
    sources = {c["source"] for c in candidates}
    assert sources == {"audiodb", "itunes"}


def test_movie_art_from_tmdb_without_arr(db_session, monkeypatch):
    monkeypatch.setattr(settings, "radarr_api_key", "")
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")
    monkeypatch.setattr(
        tmdb_source, "movie_images",
        lambda key, tmdb_id: [
            {
                "source": "tmdb",
                "ref": "/poster.jpg",
                "url": "https://image.tmdb.org/t/p/original/poster.jpg",
                "label": "TMDB poster",
            },
        ],
    )

    movie = Movie(title="The Matrix", year=1999, tmdb_id=603)
    db_session.add(movie)
    db_session.flush()

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="movie", entity_id=movie.id,
    )
    assert [c["source"] for c in candidates] == ["tmdb"]
    assert any("Radarr" in n for n in notes)


def test_one_source_failing_still_returns_others(db_session, monkeypatch):
    # Movie: TMDB succeeds, Radarr is configured but raises. TMDB result
    # survives and Radarr becomes a friendly note.
    monkeypatch.setattr(settings, "radarr_api_key", "radarrkey")
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")
    monkeypatch.setattr(
        tmdb_source, "movie_images",
        lambda key, tmdb_id: [
            {"source": "tmdb", "ref": "/p.jpg", "url": "https://x/p.jpg", "label": "TMDB poster"},
        ],
    )

    def _boom(movie):
        from app.services.arr._base import ArrClientError
        raise ArrClientError("radarr rejected API key (401)")

    monkeypatch.setattr(art_search, "_radarr_movie_images", _boom)

    movie = Movie(title="Heat", year=1995, tmdb_id=949)
    db_session.add(movie)
    db_session.flush()

    candidates, notes = art_search.search_candidates_with_notes(
        db_session, kind="movie", entity_id=movie.id,
    )
    assert any(c["source"] == "tmdb" for c in candidates)
    assert any(n == "Radarr did not answer." for n in notes)
    assert not any("401" in n for n in notes)
