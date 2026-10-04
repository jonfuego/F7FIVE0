"""/api/client/android-app (info + signed link) and /android-app/download
(bearer or signed link, stamped APK)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.api.deps import current_user, get_db
from app.api.media_files import optional_current_user
from app.config import settings
from app.main import app
from app.models.user import User
from app.services import android_app, apk_stamp
from app.services.security import hash_password
from tests.services.test_apk_stamp import _fake_signed_apk


@pytest.fixture()
def user(db_session):
    u = User(
        username="apk-user", display_name="APK User",
        password_hash=hash_password("x-strong-pass"), role="member", is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def downloads(tmp_path, monkeypatch):
    folder = tmp_path / "downloads"
    folder.mkdir()
    monkeypatch.setattr(settings, "f7five0_downloads_dir", str(folder))
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "home_url", "http://192.168.1.20:3001")
    return folder


@pytest.fixture()
def db_only(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def api(db_only, user):
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[optional_current_user] = lambda: user
    client = TestClient(app)
    yield client
    client.close()


def _stamp_of(tmp_path: Path, body: bytes) -> dict:
    out = tmp_path / "got.apk"
    out.write_bytes(body)
    return apk_stamp.read_stamp(out)


def test_find_apks_picks_newest_per_abi_and_ignores_tv(downloads):
    for name in ("F7FIVE0-1.0.0.apk", "F7FIVE0-1.2.0.apk", "F7FIVE0-1.10.0.apk",
                 "F7FIVE0-1.2.0-armv7.apk", "F7FIVE0-TV-9.0.0.apk", "notes.txt"):
        (downloads / name).write_bytes(b"x")
    found = android_app.find_apks()
    assert found["arm64"].version == "1.10.0"
    assert found["armv7"].name == "F7FIVE0-1.2.0-armv7.apk"
    assert set(found) == {"arm64", "armv7"}


def test_server_addresses_order_and_dedupe(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://Media.Example.com/")
    monkeypatch.setattr(settings, "home_url", "http://192.168.1.20:3001")
    assert android_app.server_addresses("https://media.example.com") == [
        "https://media.example.com", "http://192.168.1.20:3001",
    ]
    assert android_app.server_addresses("http://127.0.0.1:3001") == [
        "https://media.example.com", "http://192.168.1.20:3001",
    ]
    assert android_app.server_addresses("http://f7.tail1234.ts.net") == [
        "https://media.example.com", "http://f7.tail1234.ts.net", "http://192.168.1.20:3001",
    ]


def test_home_url_defaults_to_lan_ip_and_web_port(monkeypatch):
    monkeypatch.setattr(settings, "home_url", "")
    monkeypatch.setattr(settings, "web_port", 3101)
    monkeypatch.setattr(android_app, "lan_ipv4", lambda: "10.0.0.5")
    assert android_app.home_url() == "http://10.0.0.5:3101"
    monkeypatch.setattr(android_app, "lan_ipv4", lambda: None)
    assert android_app.home_url() is None


def test_info_when_nothing_published(api, downloads):
    resp = api.get("/api/client/android-app")
    assert resp.status_code == 200
    assert resp.json() == {"available": False, "abis": []}


def test_info_requires_auth(db_only, downloads):
    client = TestClient(app)
    assert client.get("/api/client/android-app").status_code == 401


def test_info_and_signed_download(api, downloads, user, tmp_path, db_only):
    _fake_signed_apk(downloads / "F7FIVE0-1.4.0.apk", [(0x7109871A, b"sig")])
    info = api.get("/api/client/android-app", headers={"host": "192.168.1.20:3001"}).json()
    assert info["available"] is True
    assert info["version"] == "1.4.0"
    assert info["abis"] == ["arm64"]
    assert info["url"].startswith("http://192.168.1.20:3001/api/client/android-app/download?")
    assert info["path"].startswith("/api/client/android-app/download?")

    # The signed link works with no bearer.
    app.dependency_overrides.pop(current_user)
    app.dependency_overrides.pop(optional_current_user)
    anon = TestClient(app)
    head = anon.head(info["path"])
    assert head.status_code == 200
    assert head.headers["x-apk-version"] == "1.4.0"
    assert int(head.headers["content-length"]) == info["size_bytes"]
    got = anon.get(info["path"], headers={"host": "192.168.1.20:3001"})
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/vnd.android.package-archive"
    assert len(got.content) == info["size_bytes"]
    assert "F7FIVE0-1.4.0.apk" in got.headers["content-disposition"]
    assert _stamp_of(tmp_path, got.content) == {
        "v": 1, "servers": ["https://media.example.com", "http://192.168.1.20:3001"],
    }

    # Tampered, wrong-ABI, and missing signatures are refused.
    q = parse_qs(urlsplit(info["path"]).query)
    bad = f"/api/client/android-app/download?abi=arm64&uid={q['uid'][0]}&exp={q['exp'][0]}&sig={'0' * 64}"
    assert anon.get(bad).status_code == 401
    other = f"/api/client/android-app/download?abi=armv7&uid={q['uid'][0]}&exp={q['exp'][0]}&sig={q['sig'][0]}"
    assert anon.get(other).status_code == 401
    assert anon.get("/api/client/android-app/download").status_code == 401


def test_expired_link_refused(db_only, downloads, user, monkeypatch):
    from app.services import security

    _fake_signed_apk(downloads / "F7FIVE0-1.4.0.apk", [(0x7109871A, b"sig")])
    monkeypatch.setattr(security, "APP_DOWNLOAD_TTL_SECONDS", -10)
    p = security.sign_app_download_params("arm64", user.id)
    client = TestClient(app)
    url = f"/api/client/android-app/download?abi=arm64&uid={p['uid']}&exp={p['exp']}&sig={p['sig']}"
    assert client.get(url).status_code == 401


def test_bearer_download_and_missing_abi(api, downloads, tmp_path):
    _fake_signed_apk(downloads / "F7FIVE0-2.0.0.apk", [(0x7109871A, b"sig")])
    got = api.get("/api/client/android-app/download")
    assert got.status_code == 200
    assert _stamp_of(tmp_path, got.content)["servers"][0] == "https://media.example.com"
    assert api.get("/api/client/android-app/download?abi=armv7").status_code == 404
    assert api.get("/api/client/android-app/download?abi=x86").status_code == 422
    assert api.get("/api/client/android-app?abi=armv7").json()["available"] is False


def test_unstampable_apk_reports_unavailable(api, downloads):
    (downloads / "F7FIVE0-1.0.0.apk").write_bytes(b"not an apk")
    assert api.get("/api/client/android-app").json()["available"] is False
    assert api.get("/api/client/android-app/download").status_code == 404
