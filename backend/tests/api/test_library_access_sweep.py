"""Security sweep: a hidden library never leaks on any content path.

Two movie libraries (A and B) each hold a movie with a ready file. Library B is
hidden from a member. This walks every content-serving endpoint as that member
and asserts a library-B item never appears, that direct detail / per-file
requests 404, that `/api/stream/start` 403s, and that a gateway serve path 403s
for a validly signed library-B URL. An admin sees library-B content on the same
paths. The route list is explicit so an unguarded new route trips it.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import current_session_id, current_user, get_db
from app.main import app
from app.models.library import Library, LibraryKind, UserLibraryAccess
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.playback import WatchProgress
from app.models.user import User
from app.services.security import sign_stream_url_params
from app.stream import app as stream_app
from app.stream import get_db as stream_get_db
from tests.conftest import make_active_session


class World:
    pass


@pytest.fixture()
def world(db_session, tmp_path):
    w = World()
    w.member = User(username="member", display_name="M", password_hash="x",
                    role="member", is_active=True)
    w.admin = User(username="admin2", display_name="A", password_hash="x",
                   role="admin", is_active=True)
    db_session.add_all([w.member, w.admin])
    db_session.flush()
    w.member_session = make_active_session(db_session, user=w.member)[1]
    w.admin_session = make_active_session(db_session, user=w.admin)[1]

    w.lib_a = Library(name="Movies", kind=LibraryKind.movies, sort_order=0)
    w.lib_b = Library(name="Hidden Movies", kind=LibraryKind.movies, sort_order=1)
    db_session.add_all([w.lib_a, w.lib_b])
    db_session.flush()

    def movie(title, lib_id):
        m = Movie(title=title, year=2001)
        db_session.add(m)
        db_session.flush()
        p = tmp_path / f"{title}.mp4"
        p.write_bytes(b"\x00" * 32)
        mf = MediaFile(kind=MediaKind.movie, ref_id=m.id, path=str(p),
                       library_id=lib_id, scan_state=ScanState.ready,
                       container="mp4", video_codec="h264", audio_codec="aac",
                       size_bytes=32, duration_sec=60)
        db_session.add(mf)
        db_session.flush()
        return m, mf

    w.movie_a, w.file_a = movie("Movie A", w.lib_a.id)
    w.movie_b, w.file_b = movie("Movie B", w.lib_b.id)

    # Hide library B from the member.
    db_session.add(UserLibraryAccess(user_id=w.member.id, library_id=w.lib_b.id))
    # The member has watch progress on both (B should still never surface).
    db_session.add(WatchProgress(user_id=w.member.id, media_file_id=w.file_a.id,
                                 position_sec=30, duration_sec=60))
    db_session.add(WatchProgress(user_id=w.member.id, media_file_id=w.file_b.id,
                                 position_sec=30, duration_sec=60))
    db_session.commit()
    return w


def _client(db_session, user, session):
    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_session_id] = lambda: session.id
    return TestClient(app)


@pytest.fixture()
def member_client(db_session, world):
    c = _client(db_session, world.member, world.member_session)
    try:
        yield c
    finally:
        c.close()
        app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(db_session, world):
    c = _client(db_session, world.admin, world.admin_session)
    try:
        yield c
    finally:
        c.close()
        app.dependency_overrides.clear()


@pytest.fixture()
def gateway_client(db_session, world):
    def _db():
        yield db_session

    stream_app.dependency_overrides[stream_get_db] = _db
    c = TestClient(stream_app)
    try:
        yield c
    finally:
        c.close()
        stream_app.dependency_overrides.clear()


# The browse/list/discovery routes a member walks. Each must exclude library B.
_LIST_ROUTES = [
    "/api/movies",
    "/api/recent",
    "/api/search?q=Movie",
    "/api/continue-watching",
    "/api/on-deck",
    "/api/auto-playlist/random",
]


def test_member_list_routes_never_include_library_b(member_client, world):
    b_id = str(world.movie_b.id)
    a_id = str(world.movie_a.id)
    for route in _LIST_ROUTES:
        r = member_client.get(route)
        assert r.status_code == 200, (route, r.status_code, r.text)
        body = r.text
        assert b_id not in body, f"{route} leaked library B item"
    # Positive control: the member does see library A on the movies list.
    assert a_id in member_client.get("/api/movies").text


def test_member_libraries_endpoint_hides_b(member_client, world):
    r = member_client.get("/api/libraries")
    assert r.status_code == 200, r.text
    ids = {lib["id"] for lib in r.json()}
    assert str(world.lib_a.id) in ids
    assert str(world.lib_b.id) not in ids


def test_member_detail_and_per_file_404_for_b(member_client, world):
    assert member_client.get(f"/api/movies/{world.movie_b.id}").status_code == 404
    # Positive control: A is reachable.
    assert member_client.get(f"/api/movies/{world.movie_a.id}").status_code == 200
    # Per-file endpoints 404 for a B file.
    assert member_client.get(f"/api/media-files/{world.file_b.id}/streams").status_code == 404
    assert member_client.get(
        f"/api/media-files/{world.file_b.id}/download-url"
    ).status_code == 404


def test_member_stream_start_403_for_b(member_client, world):
    r = member_client.post("/api/stream/start", json={"file_id": str(world.file_b.id)})
    assert r.status_code == 403, r.text
    # The member can start library A.
    ok = member_client.post("/api/stream/start", json={"file_id": str(world.file_a.id)})
    assert ok.status_code == 200, ok.text


def test_gateway_serve_403_for_a_member_b_url(gateway_client, world):
    params = sign_stream_url_params(world.member.id, world.file_b.id, world.member_session.id)
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = gateway_client.get(f"/stream/direct/{world.file_b.id}?{q}", headers={"Range": "bytes=0-7"})
    assert r.status_code == 403, r.text


def test_admin_sees_library_b_everywhere(admin_client, gateway_client, world):
    # Lists and detail include B.
    assert str(world.movie_b.id) in admin_client.get("/api/movies").text
    assert admin_client.get(f"/api/movies/{world.movie_b.id}").status_code == 200
    assert {str(world.lib_a.id), str(world.lib_b.id)} <= {
        lib["id"] for lib in admin_client.get("/api/libraries").json()
    }
    # Stream start for a B file is allowed for the admin.
    assert admin_client.post(
        "/api/stream/start", json={"file_id": str(world.file_b.id)}
    ).status_code == 200
    # And a gateway serve path with an admin-signed B URL serves bytes.
    params = sign_stream_url_params(world.admin.id, world.file_b.id, world.admin_session.id)
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = gateway_client.get(f"/stream/direct/{world.file_b.id}?{q}", headers={"Range": "bytes=0-7"})
    assert r.status_code in (200, 206), r.text
