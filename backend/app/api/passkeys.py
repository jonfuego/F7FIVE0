"""WebAuthn passkey endpoints: register, login, and credential management.

Passkeys are discoverable (resident) credentials with user verification
required, scoped to the RP id from settings (WEBAUTHN_RP_ID, or the host of an
https PUBLIC_URL) and accepted from the web origin plus each allowed Android
app's apk-key-hash origin (see `Settings.webauthn_origins_list`). When no RP id
resolves (home-only http install) every endpoint here answers 404
`passkeys_disabled` and clients hide the feature (`/api/client/features`).

Ceremony flow:
  - register/options (auth): mint a creation challenge, store it, return options.
  - register/verify (auth): verify the attestation against the stored challenge,
    persist the credential.
  - login/options (no auth): mint an assertion challenge, store it, return options.
  - login/verify (no auth): resolve the credential from the assertion, verify it
    against the stored challenge, reject sign-count regression, then issue the
    same TokenPair shape as password login honoring `client_type`.

Challenges live in the DB (`webauthn_challenges`), are single-use, and expire
after `settings.webauthn_challenge_ttl_seconds`. Sessions are only ever minted
through auth._issue_tokens.

The py_webauthn verify functions are imported at module scope so tests can
substitute a software authenticator without real attestation crypto; the
endpoint logic (challenge lifecycle, sign-count regression, auth events, token
issuance, credential CRUD) is what these endpoints own.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api.auth import (
    _issue_tokens, _log_auth_event, _login_clear, _login_record_failure,
    _login_throttle, _throttle_key,
)
from app.api.deps import current_user, get_db
from app.api.schemas import (
    PasskeyLoginVerifyRequest, PasskeyOut, PasskeyRegisterVerifyRequest,
    PasskeyRenameRequest, TokenPair,
)
from app.config import settings
from app.models.user import User
from app.models.webauthn import WebAuthnChallenge, WebAuthnCredential


log = logging.getLogger("f7five0.api.passkeys")


def _require_passkeys() -> None:
    """Passkeys need HTTPS and an RP id. Off on a home-only install."""
    if not settings.passkeys_enabled:
        raise HTTPException(status_code=404, detail="passkeys_disabled")


router = APIRouter(dependencies=[Depends(_require_passkeys)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Postgres hands tz-aware datetimes back; SQLite (tests) hands naive. Treat
    stored challenge timestamps as UTC so expiry math is backend-agnostic."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _store_challenge(db: Session, *, challenge: bytes, kind: str,
                     user_id: Optional[uuid.UUID]) -> None:
    now = _now()
    db.add(
        WebAuthnChallenge(
            challenge=bytes_to_base64url(challenge),
            user_id=user_id,
            kind=kind,
            expires_at=now + timedelta(seconds=settings.webauthn_challenge_ttl_seconds),
            created_at=now,
        )
    )


def _challenge_from_credential(credential: dict) -> str:
    """Extract the base64url challenge the authenticator signed, from the
    assertion's clientDataJSON. This is the correlation key to the stored row."""
    try:
        client_data_b64 = credential["response"]["clientDataJSON"]
        raw = base64url_to_bytes(client_data_b64)
        data = json.loads(raw.decode("utf-8"))
        challenge = data["challenge"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid_credential")
    if not isinstance(challenge, str) or not challenge:
        raise HTTPException(status_code=400, detail="invalid_credential")
    return challenge


def _consume_challenge(db: Session, *, challenge: str, kind: str,
                       user_id: Optional[uuid.UUID]) -> WebAuthnChallenge:
    """Look up and validate a stored challenge, then mark it consumed.

    Rejects a missing, expired, or already-used challenge. Distinguishing these
    (rather than a blanket 400) makes the failure modes testable and the client
    messages honest.
    """
    q = select(WebAuthnChallenge).where(
        WebAuthnChallenge.challenge == challenge,
        WebAuthnChallenge.kind == kind,
    )
    if user_id is not None:
        q = q.where(WebAuthnChallenge.user_id == user_id)
    row = db.scalar(q.order_by(WebAuthnChallenge.created_at.desc()))
    if row is None:
        raise HTTPException(status_code=400, detail="challenge_not_found")
    if row.consumed_at is not None:
        raise HTTPException(status_code=400, detail="challenge_already_used")
    if _as_utc(row.expires_at) <= _now():
        raise HTTPException(status_code=400, detail="challenge_expired")
    row.consumed_at = _now()
    return row


def _serialize_options(options) -> dict:
    """py_webauthn hands options as a JSON string; return a dict FastAPI can
    emit as a plain JSON object."""
    return json.loads(options_to_json(options))


# ---------------------------------------------------------------------------
# Registration (auth required)
# ---------------------------------------------------------------------------
@router.post("/passkey/register/options")
def register_options(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Return PublicKeyCredentialCreationOptions for a resident, UV-required
    passkey and store its challenge."""
    existing = db.scalars(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    ).all()
    exclude = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
        for c in existing
    ]
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id_effective,
        rp_name=settings.webauthn_rp_name,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.username,
        user_display_name=user.display_name,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _store_challenge(db, challenge=options.challenge, kind="register", user_id=user.id)
    db.commit()
    return _serialize_options(options)


@router.post("/passkey/register/verify", response_model=PasskeyOut, status_code=201)
def register_verify(
    body: PasskeyRegisterVerifyRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WebAuthnCredential:
    """Verify a registration attestation and persist the credential."""
    challenge_b64 = _challenge_from_credential(body.credential)
    _consume_challenge(db, challenge=challenge_b64, kind="register", user_id=user.id)

    try:
        verified = verify_registration_response(
            credential=json.dumps(body.credential),
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=settings.webauthn_rp_id_effective,
            expected_origin=settings.webauthn_origins_list,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        db.commit()  # persist the challenge consumption
        log.info("passkey registration rejected: %s", exc)
        raise HTTPException(status_code=400, detail="registration_verification_failed")

    credential_id_b64 = bytes_to_base64url(verified.credential_id)
    dupe = db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == credential_id_b64
        )
    )
    if dupe is not None:
        db.commit()
        raise HTTPException(status_code=409, detail="passkey_already_registered")

    transports = None
    raw_transports = (body.credential.get("response") or {}).get("transports")
    if isinstance(raw_transports, list) and raw_transports:
        transports = ",".join(str(t) for t in raw_transports)[:128]

    name = (body.name or "").strip() or "Passkey"
    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=credential_id_b64,
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=int(verified.sign_count or 0),
        transports=transports,
        aaguid=verified.aaguid,
        name=name,
        created_at=_now(),
    )
    db.add(cred)
    _log_auth_event(db, user_id=user.id, event="passkey_register", request=request)
    db.commit()
    db.refresh(cred)
    return cred


# ---------------------------------------------------------------------------
# Login (no auth)
# ---------------------------------------------------------------------------
@router.post("/passkey/login/options")
def login_options(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Return PublicKeyCredentialRequestOptions for a discoverable-credential
    login (empty allowCredentials, UV required) and store its challenge."""
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id_effective,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store_challenge(db, challenge=options.challenge, kind="login", user_id=None)
    db.commit()
    return _serialize_options(options)


@router.post("/passkey/login/verify", response_model=TokenPair)
def login_verify(
    body: PasskeyLoginVerifyRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenPair:
    """Verify an assertion and issue tokens. Uses the shared login throttle."""
    throttle_key = _throttle_key(request, "passkey")
    _login_throttle(throttle_key)

    challenge_b64 = _challenge_from_credential(body.credential)
    _consume_challenge(db, challenge=challenge_b64, kind="login", user_id=None)

    raw_id = body.credential.get("id") or body.credential.get("rawId")
    if not raw_id or not isinstance(raw_id, str):
        _fail_login(db, throttle_key, request, user_id=None)
        raise HTTPException(status_code=400, detail="invalid_credential")

    cred = db.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == raw_id)
    )
    if cred is None:
        _fail_login(db, throttle_key, request, user_id=None)
        raise HTTPException(status_code=401, detail="unknown_passkey")

    try:
        verified = verify_authentication_response(
            credential=json.dumps(body.credential),
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=settings.webauthn_rp_id_effective,
            expected_origin=settings.webauthn_origins_list,
            credential_public_key=base64url_to_bytes(cred.public_key),
            credential_current_sign_count=cred.sign_count,
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as exc:
        log.info("passkey assertion rejected: %s", exc)
        _fail_login(db, throttle_key, request, user_id=cred.user_id)
        raise HTTPException(status_code=401, detail="passkey_verification_failed")

    # Sign-count regression: a real (non-zero) counter that goes backwards
    # signals a cloned authenticator. Many platform authenticators report 0
    # every time; only enforce when the stored counter is non-zero.
    if cred.sign_count > 0 and verified.new_sign_count <= cred.sign_count:
        _fail_login(db, throttle_key, request, user_id=cred.user_id)
        raise HTTPException(status_code=401, detail="sign_count_regression")

    user = db.get(User, cred.user_id)
    if user is None or not user.is_active:
        _fail_login(db, throttle_key, request, user_id=cred.user_id)
        raise HTTPException(status_code=401, detail="inactive_or_unknown_user")

    _login_clear(throttle_key)
    cred.sign_count = int(verified.new_sign_count or 0)
    cred.last_used_at = _now()

    client_type = (body.client_type or "browser").strip().lower()
    if client_type not in ("browser", "pwa", "native"):
        client_type = "browser"
    tokens = _issue_tokens(
        db, user=user, device_label=body.device_name, client_type=client_type,
        platform=body.platform, client_version=body.client_version,
    )
    # Event carries the client type so the smoke check can split native vs web.
    # `passkey_login` stays the grep-able prefix (see the documented event list).
    _log_auth_event(
        db, user_id=user.id, event=f"passkey_login:{client_type}", request=request,
    )
    db.commit()
    return tokens


def _fail_login(db: Session, throttle_key, request: Request,
                *, user_id: Optional[uuid.UUID]) -> None:
    """Record a failed passkey login (throttle + audit) and commit."""
    _login_record_failure(throttle_key)
    _log_auth_event(db, user_id=user_id, event="passkey_login_failed", request=request)
    db.commit()


# ---------------------------------------------------------------------------
# Management (auth required)
# ---------------------------------------------------------------------------
@router.get("/passkeys", response_model=list[PasskeyOut])
def list_passkeys(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WebAuthnCredential]:
    return list(
        db.scalars(
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user.id)
            .order_by(WebAuthnCredential.created_at.desc())
        )
    )


@router.patch("/passkeys/{passkey_id}", response_model=PasskeyOut)
def rename_passkey(
    passkey_id: uuid.UUID,
    body: PasskeyRenameRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WebAuthnCredential:
    cred = db.get(WebAuthnCredential, passkey_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status_code=404, detail="passkey_not_found")
    cred.name = body.name.strip()
    db.commit()
    db.refresh(cred)
    return cred


@router.delete("/passkeys/{passkey_id}", status_code=204)
def delete_passkey(
    passkey_id: uuid.UUID,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    cred = db.get(WebAuthnCredential, passkey_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status_code=404, detail="passkey_not_found")
    db.delete(cred)
    _log_auth_event(db, user_id=user.id, event="passkey_delete", request=request)
    db.commit()
