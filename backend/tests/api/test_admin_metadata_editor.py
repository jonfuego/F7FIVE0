"""Admin metadata editor: PATCH + lock round-trips."""
from __future__ import annotations

import uuid

from app.models.movie import Movie
from app.models.tv import Series
from app.services import metadata_locks
from app.services.metadata import runner


def _movie(db, title="The Test", tmdb_id=None):
    m = Movie(title=title, tmdb_id=tmdb_id)
    db.add(m)
    db.commit()
    return m


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------
def test_get_returns_fields_and_empty_locks(client, db_session):
    m = _movie(db_session, "Inception", tmdb_id=27205)
    r = client.get(f"/api/admin/metadata/movie/{m.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "movie"
    assert body["entity_id"] == str(m.id)
    assert body["locked_fields"] == []
    assert body["fields"]["title"] == "Inception"


def test_get_invalid_kind_422(client, db_session):
    r = client.get(f"/api/admin/metadata/banana/{uuid.uuid4()}")
    assert r.status_code == 422


def test_get_unknown_id_404(client, db_session):
    r = client.get(f"/api/admin/metadata/movie/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH writes + auto-locks
# ---------------------------------------------------------------------------
def test_patch_writes_field_and_auto_locks(client, db_session):
    m = _movie(db_session, "Old Title")
    r = client.patch(f"/api/admin/metadata/movie/{m.id}", json={"title": "New Title"})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["title"] == "New Title"
    assert "title" in body["locked_fields"]

    # Confirm in DB.
    db_session.refresh(m)
    assert m.title == "New Title"
    assert metadata_locks.is_locked(db_session, "movie", m.id, "title")


def test_patch_multiple_fields_all_locked(client, db_session):
    m = _movie(db_session, "A Movie", tmdb_id=99)
    r = client.patch(f"/api/admin/metadata/movie/{m.id}", json={"title": "B Movie", "year": 2024})
    assert r.status_code == 200
    body = r.json()
    assert "title" in body["locked_fields"]
    assert "year" in body["locked_fields"]
    assert "overview" not in body["locked_fields"]


def test_patch_null_value_clears_nullable_column(client, db_session):
    m = _movie(db_session, "Some Movie")
    m.year = 2000
    db_session.commit()
    r = client.patch(f"/api/admin/metadata/movie/{m.id}", json={"year": None})
    assert r.status_code == 200
    db_session.refresh(m)
    assert m.year is None
    assert metadata_locks.is_locked(db_session, "movie", m.id, "year")


def test_patch_unknown_field_ignored(client, db_session):
    m = _movie(db_session, "Safe")
    r = client.patch(f"/api/admin/metadata/movie/{m.id}", json={"nonexistent_field": "x"})
    assert r.status_code == 200
    assert r.json()["locked_fields"] == []


# ---------------------------------------------------------------------------
# adopt_overrides
# ---------------------------------------------------------------------------
def test_adopt_overrides_copies_to_canonical_and_locks(client, db_session):
    m = _movie(db_session, "Old")
    m.overrides = {"title": "Override Title", "year": 2025}
    db_session.commit()

    r = client.patch(
        f"/api/admin/metadata/movie/{m.id}",
        json={"adopt_overrides": ["title"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["title"] == "Override Title"
    assert "title" in body["locked_fields"]
    # year was not adopted and should remain in overrides
    assert "year" in body["overridden_fields"]

    db_session.refresh(m)
    assert m.title == "Override Title"
    assert "title" not in (m.overrides or {})


# ---------------------------------------------------------------------------
# PATCH /locks — explicit lock/unlock
# ---------------------------------------------------------------------------
def test_patch_locks_locks_field_without_writing(client, db_session):
    m = _movie(db_session, "Locked")
    r = client.patch(
        f"/api/admin/metadata/movie/{m.id}/locks",
        json={"lock": ["overview"]},
    )
    assert r.status_code == 200
    assert "overview" in r.json()["locked_fields"]
    # Title was not touched.
    assert "title" not in r.json()["locked_fields"]
    db_session.refresh(m)
    assert m.title == "Locked"  # unchanged


def test_patch_locks_unlock_removes_lock(client, db_session):
    m = _movie(db_session, "Example")
    metadata_locks.set_locks(db_session, "movie", m.id, ["title", "year"])
    db_session.commit()

    r = client.patch(
        f"/api/admin/metadata/movie/{m.id}/locks",
        json={"unlock": ["title"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "title" not in body["locked_fields"]
    assert "year" in body["locked_fields"]


def test_patch_locks_unknown_field_silently_ignored(client, db_session):
    m = _movie(db_session, "Quiet")
    r = client.patch(
        f"/api/admin/metadata/movie/{m.id}/locks",
        json={"lock": ["not_a_lockable_field"]},
    )
    assert r.status_code == 200
    assert r.json()["locked_fields"] == []


# ---------------------------------------------------------------------------
# GET shows overridden_fields
# ---------------------------------------------------------------------------
def test_get_returns_overridden_fields(client, db_session):
    m = _movie(db_session, "Original")
    m.overrides = {"title": "Different Title"}
    db_session.commit()

    r = client.get(f"/api/admin/metadata/movie/{m.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["overridden_fields"].get("title") == "Different Title"


# ---------------------------------------------------------------------------
# Lock-aware enrichment integration: PATCH -> enrich_movie -> Fix Match
# ---------------------------------------------------------------------------
class _FakeTMDB:
    def __init__(self, title="TMDB Title"):
        self._title = title

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_movie(self, tmdb_id):
        return {
            "title": self._title,
            "overview": "Overview from TMDB",
            "genres": [{"name": "Action"}],
            "tagline": "TMDB tagline",
            "vote_average": 7.5,
            "vote_count": 500,
            "credits": {"cast": [], "crew": []},
        }


def _patch_tmdb(monkeypatch, title="TMDB Title"):
    monkeypatch.setattr(runner, "TMDBClient", lambda: _FakeTMDB(title))
    monkeypatch.setattr(
        runner, "tmdb_key",
        type("K", (), {"get": staticmethod(lambda: "key")})(),
    )


def test_enrich_after_lock_does_not_overwrite_title(client, db_session, monkeypatch):
    """After PATCH locks title, enrich_movie must not overwrite it."""
    m = _movie(db_session, "Local Title", tmdb_id=1001)

    # Lock the title via the API (also writes "Local Title" back)
    r = client.patch(f"/api/admin/metadata/movie/{m.id}", json={"title": "Local Title"})
    assert r.status_code == 200
    assert "title" in r.json()["locked_fields"]

    _patch_tmdb(monkeypatch, "TMDB Title")
    runner.enrich_movie(db_session, m.id, force=True)

    db_session.refresh(m)
    assert m.title == "Local Title"  # locked -> not overwritten


def test_enrich_after_unlock_does_overwrite_title(client, db_session, monkeypatch):
    """After locking and then unlocking title, enrich_movie writes the remote value."""
    m = _movie(db_session, "Local Title", tmdb_id=1002)

    # Lock then unlock
    client.patch(f"/api/admin/metadata/movie/{m.id}", json={"title": "Local Title"})
    r = client.patch(
        f"/api/admin/metadata/movie/{m.id}/locks",
        json={"unlock": ["title"]},
    )
    assert "title" not in r.json()["locked_fields"]

    _patch_tmdb(monkeypatch, "TMDB Title")
    runner.enrich_movie(db_session, m.id, force=True)

    db_session.refresh(m)
    assert m.title == "TMDB Title"  # unlocked -> overwritten


def test_fix_match_does_not_overwrite_locked_title(client, db_session, monkeypatch):
    """POST /api/admin/match/movie/{id} (Fix Match) must not overwrite a locked title."""
    m = _movie(db_session, "Local Title", tmdb_id=1003)

    # Lock the title
    client.patch(f"/api/admin/metadata/movie/{m.id}", json={"title": "Local Title"})

    _patch_tmdb(monkeypatch, "TMDB Title")
    r = client.post(
        f"/api/admin/match/movie/{m.id}",
        json={"source": "tmdb", "ref": "1003"},
    )
    assert r.status_code == 200

    db_session.refresh(m)
    assert m.title == "Local Title"  # locked -> not overwritten by Fix Match
