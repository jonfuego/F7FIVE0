"""Passkey configuration for a general install: RP id derived from
PUBLIC_URL, off on plain-http installs, Android origins and assetlinks built
from the configured app certificates."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.config import apk_key_hash_origin, settings
from app.main import app

CERT_HEX = "4a81d2532d208d1429e574f889187e6128e71d3a0b033f68dfb6a0b3ff84acac"
CERT_COLON = ":".join(CERT_HEX.upper()[i:i + 2] for i in range(0, 64, 2))
OLD_CERT = "F4:F8:0A:54:FF:FD:A1:24:E9:A0:92:8A:49:ED:25:83:C8:E7:97:55:76:D2:B0:A3:C3:8E:02:C7:A8:06:08:96"


@pytest.fixture()
def cfg(monkeypatch):
    def apply(**values):
        base = {
            "public_url": "",
            "webauthn_rp_id": "",
            "webauthn_origins": "",
            "webauthn_android_package": "com.f7five0.app",
            "webauthn_android_cert_sha256": "",
            "webauthn_extra_android_apps": "",
        }
        base.update(values)
        for k, v in base.items():
            monkeypatch.setattr(settings, k, v)
    return apply


@pytest.fixture()
def client(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()
        app.dependency_overrides.clear()


def test_apk_key_hash_matches_reference():
    expected = base64.urlsafe_b64encode(bytes.fromhex(CERT_HEX)).decode().rstrip("=")
    assert apk_key_hash_origin(CERT_COLON) == f"android:apk-key-hash:{expected}"
    # Value printed by scripts/release-apk.ps1 for the same certificate.
    assert expected == "SoHSUy0gjRQp5XT4iRh-YSjnHToLAz9o37ags_-ErKw"


def test_old_archive_cert_maps_to_known_origin():
    # arcHIVE 1.3.0's production origin, so the switchover can list it.
    assert apk_key_hash_origin(OLD_CERT) == (
        "android:apk-key-hash:9PgKVP_9oSTpoJKKSe0lg8jnl1V20rCjw44Cx6gGCJY"
    )


def test_rp_id_from_https_public_url(cfg):
    cfg(public_url="https://Media.Example.com/", webauthn_android_cert_sha256=CERT_HEX)
    assert settings.passkeys_enabled
    assert settings.webauthn_rp_id_effective == "media.example.com"
    assert settings.webauthn_origins_list == [
        "https://media.example.com",
        apk_key_hash_origin(CERT_COLON),
    ]


def test_public_url_port_kept_in_origin(cfg):
    cfg(public_url="https://box.example.ts.net:8443")
    assert settings.webauthn_rp_id_effective == "box.example.ts.net"
    assert settings.webauthn_origins_list == ["https://box.example.ts.net:8443"]


@pytest.mark.parametrize("url", ["", "http://192.168.1.20:3001", "http://media.example.com"])
def test_off_without_https(cfg, url):
    cfg(public_url=url, webauthn_android_cert_sha256=CERT_HEX)
    assert not settings.passkeys_enabled
    assert settings.webauthn_origins_list == []


def test_explicit_rp_id_and_origins_win(cfg):
    cfg(
        public_url="",
        webauthn_rp_id="media.fuegofam.com",
        webauthn_origins="https://media.fuegofam.com,android:apk-key-hash:abc",
        webauthn_android_cert_sha256=CERT_COLON,
    )
    assert settings.webauthn_rp_id_effective == "media.fuegofam.com"
    assert settings.webauthn_origins_list == [
        "https://media.fuegofam.com",
        "android:apk-key-hash:abc",
        apk_key_hash_origin(CERT_COLON),
    ]


def test_extra_apps_and_bad_fingerprints(cfg):
    cfg(
        public_url="https://media.example.com",
        webauthn_android_cert_sha256=f"{CERT_HEX}, not-a-cert",
        webauthn_extra_android_apps=f"com.fuegofam.archive={OLD_CERT}; junk; com.x=zz",
    )
    assert settings.webauthn_android_apps == [
        ("com.f7five0.app", [CERT_COLON]),
        ("com.fuegofam.archive", [OLD_CERT]),
    ]
    assert len(settings.webauthn_origins_list) == 3


def test_features_reports_passkeys(cfg, client):
    cfg(public_url="https://media.example.com")
    body = client.get("/api/client/features").json()
    assert body["passkeys"] == {"enabled": True, "rp_id": "media.example.com"}
    cfg(public_url="http://192.168.1.20:3001")
    body = client.get("/api/client/features").json()
    assert body["passkeys"] == {"enabled": False, "rp_id": None}


def test_assetlinks(cfg, client):
    cfg(
        public_url="https://media.example.com",
        webauthn_android_cert_sha256=CERT_HEX,
        webauthn_extra_android_apps=f"com.fuegofam.archive={OLD_CERT}",
    )
    resp = client.get("/api/client/assetlinks.json")
    assert resp.status_code == 200
    body = resp.json()
    assert [s["target"]["package_name"] for s in body] == ["com.f7five0.app", "com.fuegofam.archive"]
    assert body[0]["target"]["sha256_cert_fingerprints"] == [CERT_COLON]
    assert "delegate_permission/common.get_login_creds" in body[0]["relation"]
    cfg(public_url="")
    assert client.get("/api/client/assetlinks.json").json() == []


def test_passkey_endpoints_404_when_disabled(cfg, client):
    cfg(public_url="http://192.168.1.20:3001")
    resp = client.post("/api/auth/passkey/login/options")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "passkeys_disabled"
    # Password login route is untouched by the passkey guard.
    assert client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code != 404


def test_blank_cert_falls_back_to_official(cfg, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "OFFICIAL_ANDROID_CERT_SHA256", CERT_HEX)
    cfg(public_url="https://media.example.com", webauthn_android_cert_sha256="  ",
        webauthn_android_package="")
    assert settings.webauthn_android_apps == [("com.f7five0.app", [CERT_COLON])]
    monkeypatch.setattr(config_module, "OFFICIAL_ANDROID_CERT_SHA256", "")
    assert settings.webauthn_android_apps == []
