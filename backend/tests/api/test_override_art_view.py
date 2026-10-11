"""The Edit modal's Art tab reads its pictures from GET /api/admin/override.

art_overrides is the single source of truth for art (the library tiles read
it through resolve_art). The override view used to read only the legacy
columns (poster_path / cover_path / image_path), so an artist picture saved
through art search, upload or the auto-fill showed on the tile but the Art
tab still said "No art", even after reopening the modal.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.config import settings
from app.models.art import ENTITY_ARTIST, ENTITY_MOVIE, ROLE_BACKDROP, ROLE_POSTER, ROLE_THUMB
from app.models.movie import Movie
from app.models.music import Artist
from app.models.user import User
from app.services import art as art_service


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 30, 90)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def art_root(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(settings, "art_root", tmp_path)
    # The synthetic user the migrations seed; art rows point at it.
    db_session.add(User(
        id=art_service.SYSTEM_USER_ID, username="system", display_name="System",
        password_hash="x", role="member", is_active=False,
    ))
    db_session.commit()
    return tmp_path


def _save(db, kind, entity_id, role):
    art_service.save_upload_bytes(
        db, entity_kind=kind, entity_id=entity_id, role=role, data=_png(),
        set_by_user_id=art_service.SYSTEM_USER_ID, source_kind="upload",
    )
    db.commit()


def test_artist_thumb_from_art_overrides_shows_in_the_override_view(client, db_session, art_root):
    artist = Artist(name="Birthday Party")
    db_session.add(artist)
    db_session.commit()

    r = client.get(f"/api/admin/override/artist/{artist.id}")
    assert r.status_code == 200, r.text
    assert r.json()["canonical"]["poster_path"] is None

    _save(db_session, ENTITY_ARTIST, artist.id, ROLE_THUMB)

    r = client.get(f"/api/admin/override/artist/{artist.id}")
    assert r.status_code == 200, r.text
    poster = r.json()["canonical"]["poster_path"]
    assert poster.startswith(f"/api/art/artist/{artist.id}/thumb?v=")


def test_movie_poster_and_backdrop_from_art_overrides(client, db_session, art_root):
    movie = Movie(title="Heat", poster_path="/legacy/poster.jpg")
    db_session.add(movie)
    db_session.commit()

    # No override row: the legacy column still answers.
    r = client.get(f"/api/admin/override/movie/{movie.id}")
    assert r.json()["canonical"]["poster_path"] == "/legacy/poster.jpg"

    _save(db_session, ENTITY_MOVIE, movie.id, ROLE_POSTER)
    _save(db_session, ENTITY_MOVIE, movie.id, ROLE_BACKDROP)

    canonical = client.get(f"/api/admin/override/movie/{movie.id}").json()["canonical"]
    assert canonical["poster_path"].startswith(f"/api/art/movie/{movie.id}/poster?v=")
    assert canonical["backdrop_path"].startswith(f"/api/art/movie/{movie.id}/backdrop?v=")
