"""WebAuthn passkey endpoint tests.

These drive the real register/login/manage endpoints against the in-memory
SQLite DB from conftest. The py_webauthn attestation/assertion crypto is
replaced with a software stand-in (monkeypatched verify functions) so the tests
own what these endpoints actually own: challenge lifecycle (single-use,
expiry), sign-count regression, origin rejection, auth events, token issuance,
and credential CRUD. Real attestation crypto is exercised by py_webauthn's own
test suite; re-testing it here would only test the library.
"""
from __future__ import annotations

import base64
import json
import types

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_module
from app.api import passkeys as passkeys_module
from app.api.deps import current_user, get_db
from app.main import app
from app.models.user import User, UserRole
from app.models.webauthn import WebAuthnChallenge, WebAuthnCredential
from app.services.security import hash_password
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

PASSWORD = "passkey-user-pw-1234"
CRED_ID_BYTES = b"cred-id-0001-abcdefghij"
CRED_ID_B64 = bytes_to_base64url(CRED_ID_BYTES)
PUBKEY_B64 = bytes_to_base64url(b"cose-public-key-bytes-here")


TEST_CERT = "AB:" * 31 + "AB"


@pytest.fixture(autouse=True)
def _passkeys_on(monkeypatch):
    """Passkeys need an https PUBLIC_URL (or WEBAUTHN_RP_ID). Point the
    settings at a test domain so the RP id resolves for every test here."""
    from app.config import settings

    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    monkeypatch.setattr(settings, "webauthn_rp_id", "")
    monkeypatch.setattr(settings, "webauthn_origins", "")
    monkeypatch.setattr(settings, "webauthn_android_cert_sha256", TEST_CERT)
    monkeypatch.setattr(settings, "webauthn_extra_android_apps", "")
    yield


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """The login throttle is in-process module state shared across tests; clear
    it so one test's failed-login attempts can't trip another's 429."""
    auth_module._login_failures.clear()
    yield
    auth_module._login_failures.clear()


@pytest.fixture()
def user(db_session):
    u = User(
        username="passkey-user",
        display_name="Passkey User",
        password_hash=hash_password(PASSWORD),
        role=UserRole.member,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def auth_client(db_session, user):
    """TestClient authenticated as `user` (register + manage endpoints)."""
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = lambda: user
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.fixture()
def anon_client(db_session):
    """Unauthenticated TestClient (login endpoints)."""
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


def _client_data(challenge_b64: str, *, ceremony: str,
                 origin: str = "https://media.example.com") -> str:
    """Build a base64url clientDataJSON echoing the ceremony's challenge, the
    way a real authenticator does."""
    data = {"type": ceremony, "challenge": challenge_b64, "origin": origin}
    raw = json.dumps(data).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _seed_credential(db, user, *, sign_count: int = 0) -> WebAuthnCredential:
    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=CRED_ID_B64,
        public_key=PUBKEY_B64,
        sign_count=sign_count,
        transports="internal",
        aaguid="00000000-0000-0000-0000-000000000000",
        name="Pixel",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db.add(cred)
    db.commit()
    return cred


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def test_register_options_requires_uv_and_resident_key(auth_client, db_session):
    resp = auth_client.post("/api/auth/passkey/register/options")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sel = body["authenticatorSelection"]
    assert sel["residentKey"] == "required"
    assert sel["userVerification"] == "required"
    # The challenge is persisted for verify.
    assert db_session.query(WebAuthnChallenge).filter_by(kind="register").count() == 1


def test_register_verify_persists_credential(auth_client, db_session, user, monkeypatch):
    opts = auth_client.post("/api/auth/passkey/register/options").json()
    challenge = opts["challenge"]

    monkeypatch.setattr(
        passkeys_module, "verify_registration_response",
        lambda **kw: types.SimpleNamespace(
            credential_id=CRED_ID_BYTES,
            credential_public_key=b"cose-public-key-bytes-here",
            sign_count=0,
            aaguid="00000000-0000-0000-0000-000000000000",
        ),
    )
    credential = {
        "id": CRED_ID_B64,
        "rawId": CRED_ID_B64,
        "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(challenge, ceremony="webauthn.create"),
            "attestationObject": "dummy",
            "transports": ["internal", "hybrid"],
        },
    }
    resp = auth_client.post(
        "/api/auth/passkey/register/verify",
        json={"credential": credential, "name": "My Pixel"},
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["name"] == "My Pixel"
    # Secret hygiene: the credential id and public key are never returned.
    assert "public_key" not in out and "credential_id" not in out
    cred = db_session.query(WebAuthnCredential).filter_by(user_id=user.id).one()
    assert cred.credential_id == CRED_ID_B64
    assert cred.transports == "internal,hybrid"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def _do_login(anon_client, db_session, monkeypatch, *, new_sign_count=1,
              client_type=None, credential_overrides=None):
    opts = anon_client.post("/api/auth/passkey/login/options").json()
    challenge = opts["challenge"]
    monkeypatch.setattr(
        passkeys_module, "verify_authentication_response",
        lambda **kw: types.SimpleNamespace(new_sign_count=new_sign_count),
    )
    credential = {
        "id": CRED_ID_B64,
        "rawId": CRED_ID_B64,
        "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(challenge, ceremony="webauthn.get"),
            "authenticatorData": "dummy",
            "signature": "dummy",
            "userHandle": "dummy",
        },
    }
    if credential_overrides:
        credential.update(credential_overrides)
    payload = {"credential": credential}
    if client_type is not None:
        payload["client_type"] = client_type
        payload["device_name"] = "Pixel Test"
        payload["platform"] = "android"
        payload["client_version"] = "1.3.0"
    return anon_client.post("/api/auth/passkey/login/verify", json=payload), challenge


def test_login_verify_success_returns_tokens(anon_client, db_session, user, monkeypatch):
    _seed_credential(db_session, user, sign_count=0)
    resp, _ = _do_login(anon_client, db_session, monkeypatch, new_sign_count=1)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"
    # sign count advanced on the stored credential.
    db_session.expire_all()
    assert db_session.query(WebAuthnCredential).one().sign_count == 1


def test_login_verify_native_client_type_gets_sliding_window(anon_client, db_session, user, monkeypatch):
    from app.services.security import NATIVE_REFRESH_DAYS
    _seed_credential(db_session, user, sign_count=0)
    resp, _ = _do_login(
        anon_client, db_session, monkeypatch, new_sign_count=1, client_type="native",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["refresh_expires_in_seconds"] == NATIVE_REFRESH_DAYS * 86400


def test_login_bad_origin_rejected(anon_client, db_session, user, monkeypatch):
    _seed_credential(db_session, user, sign_count=0)
    opts = anon_client.post("/api/auth/passkey/login/options").json()
    challenge = opts["challenge"]

    def _raise(**kw):
        raise InvalidAuthenticationResponse("origin mismatch")

    monkeypatch.setattr(passkeys_module, "verify_authentication_response", _raise)
    credential = {
        "id": CRED_ID_B64,
        "rawId": CRED_ID_B64,
        "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(
                challenge, ceremony="webauthn.get", origin="https://evil.example.com",
            ),
            "authenticatorData": "dummy",
            "signature": "dummy",
        },
    }
    resp = anon_client.post(
        "/api/auth/passkey/login/verify", json={"credential": credential},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "passkey_verification_failed"


def test_login_expired_challenge_rejected(anon_client, db_session, user, monkeypatch):
    from datetime import datetime, timedelta, timezone
    _seed_credential(db_session, user, sign_count=0)
    opts = anon_client.post("/api/auth/passkey/login/options").json()
    challenge = opts["challenge"]
    # Age the stored challenge past its TTL.
    row = db_session.query(WebAuthnChallenge).filter_by(kind="login").one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    monkeypatch.setattr(
        passkeys_module, "verify_authentication_response",
        lambda **kw: types.SimpleNamespace(new_sign_count=1),
    )
    credential = {
        "id": CRED_ID_B64, "rawId": CRED_ID_B64, "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(challenge, ceremony="webauthn.get"),
            "authenticatorData": "dummy", "signature": "dummy",
        },
    }
    resp = anon_client.post(
        "/api/auth/passkey/login/verify", json={"credential": credential},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "challenge_expired"


def test_login_reused_challenge_rejected(anon_client, db_session, user, monkeypatch):
    _seed_credential(db_session, user, sign_count=0)
    # First login consumes the challenge.
    resp1, challenge = _do_login(anon_client, db_session, monkeypatch, new_sign_count=1)
    assert resp1.status_code == 200, resp1.text
    # Replaying the same assertion (same, now-consumed challenge) is rejected
    # before any crypto runs.
    credential = {
        "id": CRED_ID_B64, "rawId": CRED_ID_B64, "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(challenge, ceremony="webauthn.get"),
            "authenticatorData": "dummy", "signature": "dummy",
        },
    }
    resp2 = anon_client.post(
        "/api/auth/passkey/login/verify", json={"credential": credential},
    )
    assert resp2.status_code == 400
    assert resp2.json()["detail"] == "challenge_already_used"


def test_login_sign_count_regression_rejected(anon_client, db_session, user, monkeypatch):
    # Stored counter is 5; an assertion reporting <= 5 signals a clone.
    _seed_credential(db_session, user, sign_count=5)
    resp, _ = _do_login(anon_client, db_session, monkeypatch, new_sign_count=5)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "sign_count_regression"


def test_login_unknown_passkey_rejected(anon_client, db_session, user, monkeypatch):
    # No credential seeded: the assertion resolves to nothing.
    resp, _ = _do_login(anon_client, db_session, monkeypatch, new_sign_count=1)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "unknown_passkey"


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------
def test_list_rename_delete_passkey(auth_client, db_session, user):
    cred = _seed_credential(db_session, user, sign_count=0)

    listed = auth_client.get("/api/auth/passkeys")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["name"] == "Pixel"

    renamed = auth_client.patch(
        f"/api/auth/passkeys/{cred.id}", json={"name": "Work Pixel"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Work Pixel"

    deleted = auth_client.delete(f"/api/auth/passkeys/{cred.id}")
    assert deleted.status_code == 204
    assert db_session.query(WebAuthnCredential).count() == 0


def test_delete_other_users_passkey_is_404(auth_client, db_session, user):
    other = User(
        username="other-user", display_name="Other",
        password_hash=hash_password(PASSWORD), role=UserRole.member, is_active=True,
    )
    db_session.add(other)
    db_session.commit()
    from datetime import datetime, timezone
    cred = WebAuthnCredential(
        user_id=other.id, credential_id="other-cred", public_key="k",
        sign_count=0, name="Other Key",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(cred)
    db_session.commit()

    resp = auth_client.delete(f"/api/auth/passkeys/{cred.id}")
    assert resp.status_code == 404
