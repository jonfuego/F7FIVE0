"""Tests for the NAS sign-in service and its admin endpoints.

The DPAPI layer (_protect / _unprotect) and the WNet layer (_wnet_add /
_wnet_cancel) are stubbed so the logic runs the same on Linux CI and on
Windows. Nothing here touches a real network share or real DPAPI, and no
test ever stores or asserts a plaintext password lands anywhere it
shouldn't.
"""
from __future__ import annotations

import json

import pytest

from app.services import app_settings, library_folders, nas_auth

# A password we never want to see in any stored value, response, or log.
SECRET_PW = "hunter2-do-not-leak"
SHARE_PATH = r"\\fuegonas\The Hive\Movies"
REMOTE = r"\\fuegonas\The Hive"


@pytest.fixture()
def stub_layers(monkeypatch):
    """Replace DPAPI + WNet with in-memory fakes and record WNet calls.

    _protect wraps the plaintext in a recognizable envelope so a test can
    prove the stored value is the ciphertext, not the password.
    """
    calls: list[tuple[str, str]] = []

    def fake_protect(plaintext: str) -> bytes:
        return b"ENC::" + plaintext.encode("utf-8")

    def fake_unprotect(blob: bytes) -> str:
        return blob[len(b"ENC::"):].decode("utf-8")

    def fake_add(remote: str, username: str, password: str) -> int:
        calls.append(("add", remote))
        return 0

    def fake_cancel(remote: str) -> int:
        calls.append(("cancel", remote))
        return 0

    monkeypatch.setattr(nas_auth, "_protect", fake_protect)
    monkeypatch.setattr(nas_auth, "_unprotect", fake_unprotect)
    monkeypatch.setattr(nas_auth, "_wnet_add", fake_add)
    monkeypatch.setattr(nas_auth, "_wnet_cancel", fake_cancel)
    monkeypatch.setattr(nas_auth, "is_windows", lambda: True)
    monkeypatch.setattr(nas_auth, "available", lambda: True)
    return calls


@pytest.fixture()
def one_unc_folder(monkeypatch):
    """Pretend Admin configured a single UNC Movies folder on \\fuegonas."""
    monkeypatch.setattr(
        library_folders, "all_folders",
        lambda db: {"movies": [SHARE_PATH], "tv": [], "music": [], "music_videos": []},
    )


# ---------------------------------------------------------------------------
# UNC parsing
# ---------------------------------------------------------------------------
def test_split_unc_to_server_and_share():
    assert nas_auth.split_unc(r"\\fuegonas\The Hive\Movies") == ("fuegonas", "The Hive")
    assert nas_auth.split_unc(r"\\FuegoNAS\The Hive") == ("fuegonas", "The Hive")
    assert nas_auth.server_of(r"\\FUEGONAS\The Hive\Movies\Action") == "fuegonas"
    assert nas_auth.remote_name(r"\\fuegonas\The Hive\Movies") == REMOTE
    assert nas_auth.is_unc_path(SHARE_PATH) is True
    assert nas_auth.is_unc_path(r"D:\Movies") is False
    with pytest.raises(ValueError):
        nas_auth.split_unc(r"D:\Movies")


# ---------------------------------------------------------------------------
# Save then read back, no secret leaks
# ---------------------------------------------------------------------------
def test_save_then_read_back_without_secret(db_session, stub_layers, one_unc_folder):
    result = nas_auth.save(db_session, "fuegonas", "f7five0-test", SECRET_PW)
    db_session.commit()

    # The per-share status covers the one known share, connected ok.
    shares = {s["share"]: s for s in result["shares"]}
    assert REMOTE in shares
    assert shares[REMOTE]["reason"] == "ok"

    # GET-shape listing has the username but no secret field.
    listing = nas_auth.list_servers(db_session)
    assert listing == [
        {"server": "fuegonas", "username": "f7five0-test", "updated_at": result["updated_at"]}
    ]
    assert "secret" not in listing[0]
    assert SECRET_PW not in json.dumps(listing)

    # The stored app_settings row holds ciphertext, never the plaintext.
    stored = app_settings.get(db_session, nas_auth.SETTING_KEY)
    assert "fuegonas" in stored
    assert stored["fuegonas"]["username"] == "f7five0-test"
    assert stored["fuegonas"]["secret"]
    assert SECRET_PW not in json.dumps(stored)
    # Round-trips back through the stubbed DPAPI layer.
    assert nas_auth.username_for(db_session, SHARE_PATH) == "f7five0-test"


# ---------------------------------------------------------------------------
# Change sign-in cancels before it connects (avoids error 1219)
# ---------------------------------------------------------------------------
def test_change_cancels_before_connecting(db_session, stub_layers, one_unc_folder):
    nas_auth.save(db_session, "fuegonas", "old-user", "old-pw")
    db_session.commit()
    stub_layers.clear()

    nas_auth.save(db_session, "fuegonas", "new-user", "new-pw")
    db_session.commit()

    # For the one known share, the cancel must come before the connect.
    assert ("cancel", REMOTE) in stub_layers
    assert ("add", REMOTE) in stub_layers
    assert stub_layers.index(("cancel", REMOTE)) < stub_layers.index(("add", REMOTE))


# ---------------------------------------------------------------------------
# Delete cancels the connections for that server
# ---------------------------------------------------------------------------
def test_delete_cancels_connections(db_session, stub_layers, one_unc_folder):
    nas_auth.save(db_session, "fuegonas", "f7five0-test", SECRET_PW)
    db_session.commit()
    stub_layers.clear()

    nas_auth.remove(db_session, "fuegonas")
    db_session.commit()

    assert ("cancel", REMOTE) in stub_layers
    assert nas_auth.list_servers(db_session) == []
    assert app_settings.get(db_session, nas_auth.SETTING_KEY) in (None, {})


# ---------------------------------------------------------------------------
# ensure_all connects every UNC library folder that has a saved sign-in
# ---------------------------------------------------------------------------
def test_ensure_all_connects_known_shares(db_session, stub_layers, one_unc_folder):
    nas_auth.save(db_session, "fuegonas", "f7five0-test", SECRET_PW)
    db_session.commit()
    stub_layers.clear()

    nas_auth.ensure_all(db_session)
    assert ("add", REMOTE) in stub_layers


# ---------------------------------------------------------------------------
# Windows error code -> reason mapping
# ---------------------------------------------------------------------------
def test_reason_for_code_mapping():
    assert nas_auth.reason_for_code(0) == "ok"
    assert nas_auth.reason_for_code(86) == "bad_credentials"
    assert nas_auth.reason_for_code(1326) == "bad_credentials"
    assert nas_auth.reason_for_code(53) == "unreachable"
    assert nas_auth.reason_for_code(1231) == "unreachable"
    assert nas_auth.reason_for_code(67) == "share_not_found"
    assert nas_auth.reason_for_code(5) == "access_denied"
    assert nas_auth.reason_for_code(1219) == "credential_conflict"
    assert nas_auth.reason_for_code(1327) == "account_blocked"
    assert nas_auth.reason_for_code(1331) == "account_blocked"
    assert nas_auth.reason_for_code(1909) == "account_blocked"
    # Anything unmapped falls through to a generic error that keeps the number.
    assert nas_auth.reason_for_code(99999) == "error"
    assert "99999" in nas_auth.reason_text("error", 99999)


# ---------------------------------------------------------------------------
# Admin API: list / save / delete, admin-only, and the non-Windows 501 path
# ---------------------------------------------------------------------------
def test_api_roundtrip_hides_password(client, db_session, stub_layers, one_unc_folder):
    put = client.put(
        "/api/admin/nas-credentials/fuegonas",
        json={"username": "f7five0-test", "password": SECRET_PW},
    )
    assert put.status_code == 200, put.text
    assert SECRET_PW not in put.text
    assert "secret" not in put.text.lower()

    got = client.get("/api/admin/nas-credentials")
    assert got.status_code == 200
    assert SECRET_PW not in got.text
    body = got.json()
    assert body[0]["server"] == "fuegonas"
    assert body[0]["username"] == "f7five0-test"
    assert "secret" not in body[0] and "password" not in body[0]

    # The value persisted in app_settings carries no plaintext either.
    stored = app_settings.get(db_session, nas_auth.SETTING_KEY)
    assert SECRET_PW not in json.dumps(stored)

    deleted = client.delete("/api/admin/nas-credentials/fuegonas")
    assert deleted.status_code == 200
    assert client.get("/api/admin/nas-credentials").json() == []


def test_api_requires_admin(client):
    from fastapi import HTTPException

    from app.api.deps import require_admin
    from app.main import app

    def deny():
        raise HTTPException(status_code=403, detail="admin_required")

    app.dependency_overrides[require_admin] = deny
    try:
        assert client.get("/api/admin/nas-credentials").status_code == 403
        assert client.put(
            "/api/admin/nas-credentials/fuegonas",
            json={"username": "x", "password": "y"},
        ).status_code == 403
        assert client.delete("/api/admin/nas-credentials/fuegonas").status_code == 403
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_api_501_on_non_windows(client, monkeypatch):
    monkeypatch.setattr(nas_auth, "available", lambda: False)
    monkeypatch.setattr(nas_auth, "is_windows", lambda: False)
    put = client.put(
        "/api/admin/nas-credentials/fuegonas",
        json={"username": "f7five0-test", "password": SECRET_PW},
    )
    assert put.status_code == 501
    assert put.json()["detail"] == "nas_sign_in_windows_only"
    # ensure_all is a no-op off Windows; it must not raise.
    nas_auth.ensure_all(None)
