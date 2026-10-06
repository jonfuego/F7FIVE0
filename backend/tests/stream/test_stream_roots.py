"""SEC-P0-4: the stream gateway derives its allowed roots from the active
library-folder configuration (plus STREAM_ALLOWED_ROOTS) and fails closed.

`ensure_under_roots` is the containment primitive. These cover the empty,
inside, outside, `..` traversal, sibling-prefix, Windows drive-letter case,
UNC, and symlink/junction-escape cases, plus end-to-end fail-closed behaviour
and that roots really come from the library folders.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services.range_response import ensure_under_roots
from app.services.security import sign_stream_url_params
from app.stream import _allowed_roots
from app.stream import app as stream_app
from app.stream import get_db as stream_get_db


# ---------------------------------------------------------------------------
# ensure_under_roots primitive
# ---------------------------------------------------------------------------
def test_empty_roots_rejects_everything(tmp_path):
    with pytest.raises(HTTPException) as ei:
        ensure_under_roots(tmp_path / "movie.mkv", [])
    assert ei.value.status_code == 403


def test_inside_root_allowed(tmp_path):
    root = tmp_path / "media"
    (root / "Movies").mkdir(parents=True)
    f = root / "Movies" / "a.mkv"
    f.write_bytes(b"x")
    assert ensure_under_roots(f, [root]) == f.resolve()


def test_outside_root_rejected(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    other = tmp_path / "elsewhere" / "a.mkv"
    other.parent.mkdir()
    other.write_bytes(b"x")
    with pytest.raises(HTTPException):
        ensure_under_roots(other, [root])


def test_dotdot_traversal_rejected(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"x")
    with pytest.raises(HTTPException):
        ensure_under_roots(root / ".." / "secret.txt", [root])


def test_sibling_prefix_not_confused(tmp_path):
    # "media" must not be treated as containing "media-evil".
    root = tmp_path / "media"
    root.mkdir()
    evil = tmp_path / "media-evil"
    evil.mkdir()
    f = evil / "a.mkv"
    f.write_bytes(b"x")
    with pytest.raises(HTTPException):
        ensure_under_roots(f, [root])


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
def test_drive_letter_and_path_case_insensitive():
    # Same location, different drive-letter and path casing: allowed.
    assert ensure_under_roots(Path(r"C:\Media\Movies\a.mkv"), [Path(r"c:\media")])


@pytest.mark.skipif(os.name != "nt", reason="UNC paths are Windows-only")
def test_unc_root_allowed():
    assert ensure_under_roots(Path(r"\\nas\media\Movies\a.mkv"), [Path(r"\\NAS\Media")])


def test_symlink_pointing_outside_root_rejected(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.mkv"
    target.write_bytes(b"x")
    link = root / "link.mkv"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink on this OS/privilege level: {exc}")
    # The link lives under the root, but resolve() follows it to the outside
    # target, so it is rejected.
    with pytest.raises(HTTPException):
        ensure_under_roots(link, [root])


# ---------------------------------------------------------------------------
# Root derivation + end-to-end fail-closed
# ---------------------------------------------------------------------------
def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def test_allowed_roots_derived_from_library_folders(db_session, tmp_path, monkeypatch):
    from app.config import settings

    movies = tmp_path / "Movies"
    monkeypatch.setattr(settings, "library_root_movies", str(movies))
    monkeypatch.setattr(settings, "library_root_tv", "")
    monkeypatch.setattr(settings, "library_root_music", "")
    monkeypatch.setattr(settings, "library_root_music_videos", "")
    monkeypatch.setattr(settings, "stream_allowed_roots", "")
    roots = _allowed_roots(db_session)
    assert any(_norm(movies) == _norm(r) for r in roots)


def test_allowed_roots_includes_explicit_stream_roots(db_session, tmp_path, monkeypatch):
    from app.config import settings

    extra = tmp_path / "Extra"
    monkeypatch.setattr(settings, "library_root_movies", "")
    monkeypatch.setattr(settings, "library_root_tv", "")
    monkeypatch.setattr(settings, "library_root_music", "")
    monkeypatch.setattr(settings, "library_root_music_videos", "")
    monkeypatch.setattr(settings, "stream_allowed_roots", str(extra))
    roots = _allowed_roots(db_session)
    assert any(_norm(extra) == _norm(r) for r in roots)


@pytest.fixture()
def stream_client(db_session):
    def _override_db():
        yield db_session

    stream_app.dependency_overrides[stream_get_db] = _override_db
    c = TestClient(stream_app)
    try:
        yield c
    finally:
        c.close()
        stream_app.dependency_overrides.clear()


def _mk_media(db_session, path) -> MediaFile:
    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=uuid.uuid4(),
        path=str(path),
        container="mp4",
        size_bytes=16,
        duration_sec=1,
        scan_state=ScanState.ready,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


def _signed(mf) -> str:
    params = sign_stream_url_params(uuid.uuid4(), mf.id)
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/stream/direct/{mf.id}?{q}"


def _clear_roots(monkeypatch):
    from app.config import settings

    for k in ("library_root_movies", "library_root_tv", "library_root_music",
              "library_root_music_videos", "stream_allowed_roots"):
        monkeypatch.setattr(settings, k, "")
    monkeypatch.setattr(settings, "stream_unsafe_allow_any_path", False)


def test_direct_play_fails_closed_with_no_roots(stream_client, db_session, tmp_path, monkeypatch):
    _clear_roots(monkeypatch)
    p = tmp_path / "x.mp4"
    p.write_bytes(b"\x00" * 16)
    mf = _mk_media(db_session, p)
    resp = stream_client.get(_signed(mf), headers={"Range": "bytes=0-7"})
    assert resp.status_code == 403


def test_direct_play_allowed_when_under_configured_root(stream_client, db_session, tmp_path, monkeypatch):
    from app.config import settings

    _clear_roots(monkeypatch)
    monkeypatch.setattr(settings, "stream_allowed_roots", str(tmp_path))
    p = tmp_path / "x.mp4"
    p.write_bytes(b"\x00" * 16)
    mf = _mk_media(db_session, p)
    resp = stream_client.get(_signed(mf), headers={"Range": "bytes=0-7"})
    assert resp.status_code == 206
