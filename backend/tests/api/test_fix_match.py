"""Fix Match candidate search beyond *arr (punch-list item 6).

With no *arr configured, an artist lookup still returns MusicBrainz
results, and when one source fails the others' results still come back.
The admin TestClient fixture signs in as an admin; settings default to no
*arr key, so these tests exercise the *arr-optional path directly.
"""
from __future__ import annotations

from app.api import admin
from app.config import settings
from app.models.music import Artist
from app.models.movie import Movie
from app.services import tmdb_key


class _FakeMB:
    """Stand-in for MusicBrainzClient. `artists` is what search returns;
    set `raise_on_search` to simulate a provider outage."""

    artists: list[dict] = []
    raise_on_search = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def search_artists(self, query, limit=10):
        if _FakeMB.raise_on_search:
            from app.services.metadata._base import ProviderError
            raise ProviderError("musicbrainz down")
        return _FakeMB.artists

    def search_release_groups(self, query, limit=10):
        return []


def _seed_artist(db) -> Artist:
    artist = Artist(name="Bauhaus")
    db.add(artist)
    db.flush()
    return artist


def test_artist_lookup_returns_musicbrainz_without_arr(
    client, db_session, monkeypatch,
):
    # No *arr key and no TMDB key: MusicBrainz is the only source and it
    # needs none.
    monkeypatch.setattr(settings, "lidarr_api_key", "")
    _FakeMB.artists = [
        {
            "id": "ec3b23be-4a2c-4db8-9e20-5f1d1e5e8e9a",
            "name": "Bauhaus",
            "type": "Group",
            "country": "GB",
            "disambiguation": "English goth rock band",
        },
    ]
    _FakeMB.raise_on_search = False
    monkeypatch.setattr(admin, "MusicBrainzClient", _FakeMB)

    artist = _seed_artist(db_session)
    r = client.get(
        f"/api/admin/match/artist/{artist.id}/candidates",
        params={"q": "Bauhaus"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    sources = {c["source"] for c in body["candidates"]}
    assert "musicbrainz" in sources
    assert body["candidates"][0]["ref"] == "ec3b23be-4a2c-4db8-9e20-5f1d1e5e8e9a"
    # Lidarr is not set up, so a soft callout points at connecting it.
    assert any("Lidarr" in note for note in body["notes"])
    # Not a raw error code.
    assert not any("lookup_failed" in note for note in body["notes"])


def test_one_source_failing_still_returns_others(
    client, db_session, monkeypatch,
):
    # Movie kind: TMDB returns a hit, Radarr is configured but fails. The
    # TMDB result must still come back, with a friendly note for Radarr.
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")
    monkeypatch.setattr(settings, "radarr_api_key", "radarrkey")

    class _FakeTMDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def search_many(self, kind, query, limit=10):
            return [
                {
                    "id": 603,
                    "title": "The Matrix",
                    "release_date": "1999-03-30",
                    "overview": "A hacker learns the truth.",
                    "poster_path": "/abc.jpg",
                },
            ]

    def _boom(q):
        from app.services.arr._base import ArrClientError
        raise ArrClientError("radarr rejected API key (401)")

    monkeypatch.setattr(admin, "TMDBClient", _FakeTMDB)
    monkeypatch.setattr(admin, "_radarr_search", _boom)

    movie = Movie(title="The Matrix", year=1999)
    db_session.add(movie)
    db_session.flush()

    r = client.get(
        f"/api/admin/match/movie/{movie.id}/candidates",
        params={"q": "The Matrix"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # TMDB result survived the Radarr failure.
    assert any(c["source"] == "tmdb" and c["ref"] == "603" for c in body["candidates"])
    # Radarr failure became a friendly note, not a 502 or raw code.
    assert any("Radarr did not answer." == note for note in body["notes"])
    assert not any("401" in note for note in body["notes"])


class _FakeMBEnrich:
    """Stand-in for MusicBrainzClient on the enrich path (runner.py)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_artist(self, mbid):
        return {
            "id": mbid,
            "name": "Bauhaus",
            "type": "Group",
            "country": "GB",
            "life-span": {"begin": "1978", "ended": False},
            "relations": [],
            "annotation": "English goth rock band.",
        }


def test_artist_rematch_with_musicbrainz_candidate_changes_mbid(
    client, db_session, monkeypatch,
):
    # The body the web Confirm sends: a MusicBrainz candidate's source and
    # ref, picked verbatim from the candidates list. All HTTP is mocked.
    from app.services.metadata import runner

    monkeypatch.setattr(runner, "MusicBrainzClient", _FakeMBEnrich)
    old_mbid = "11111111-1111-4111-8111-111111111111"
    new_mbid = "ec3b23be-4a2c-4db8-9e20-5f1d1e5e8e9a"
    artist = Artist(name="Bauhaus", mbid=old_mbid)
    db_session.add(artist)
    db_session.flush()

    r = client.post(
        f"/api/admin/match/artist/{artist.id}",
        json={"source": "musicbrainz", "ref": new_mbid},
    )
    assert r.status_code // 100 == 2, r.text
    db_session.refresh(artist)
    assert artist.mbid == new_mbid
    assert artist.mbid != old_mbid
    # The synchronous refresh ran against the new id.
    assert artist.metadata_status == "ok"
    assert artist.country == "GB"


def test_artist_rematch_to_an_id_another_artist_holds_is_409(
    client, db_session,
):
    # mbid is unique. Pinning one a second artist already holds used to
    # escape the commit as a 500; it is now a clear 409 and nothing changes.
    taken = "ec3b23be-4a2c-4db8-9e20-5f1d1e5e8e9a"
    db_session.add(Artist(name="Bauhaus", mbid=taken))
    other = Artist(name="Bauhaus (dup)")
    db_session.add(other)
    # Commit so the endpoint's rollback only undoes the failed write.
    db_session.commit()

    r = client.post(
        f"/api/admin/match/artist/{other.id}",
        json={"source": "musicbrainz", "ref": taken},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"].startswith("already_matched")
    db_session.refresh(other)
    assert other.mbid is None
