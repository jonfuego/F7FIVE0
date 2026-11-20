"""Password hashing (app/services/security.py): argon2id for new hashes, legacy
bcrypt-over-SHA-256 still verifies, and a legacy hash is marked for rehash.

`_old_hash` rebuilds the pre-argon2 format on its own (not through the module),
so these tests fail if the legacy branch stops accepting real stored hashes.
"""
from __future__ import annotations

import base64
import hashlib

import bcrypt
import pytest
from argon2 import PasswordHasher

from app.services import security
from app.services.security import (
    hash_password, password_needs_rehash, verify_login_password, verify_password,
)

PW = "correct horse battery staple"


def _old_hash(plaintext: str, rounds: int = 4) -> str:
    # The format hash_password wrote before argon2id (cost lowered for speed;
    # the cost is read from the hash, so verification is the same code path).
    pre = base64.b64encode(hashlib.sha256(plaintext.encode("utf-8")).digest())
    return bcrypt.hashpw(pre, bcrypt.gensalt(rounds=rounds)).decode("ascii")


def test_new_hashes_are_argon2id():
    h = hash_password(PW)
    assert h.startswith("$argon2id$")
    assert verify_password(PW, h)
    assert not verify_password(PW + "x", h)
    assert not password_needs_rehash(h)


def test_each_hash_is_salted():
    assert hash_password(PW) != hash_password(PW)


@pytest.mark.parametrize("pw", [
    "p\u00e4ssw\u00f6rd-\u00fcn\u00ef",
    "x" * 200,  # past bcrypt's 72 bytes: the argon2 side has no limit
])
def test_unicode_and_long_passwords(pw):
    h = hash_password(pw)
    assert verify_password(pw, h)
    assert not verify_password(pw[:-1], h)


def test_long_passwords_that_share_72_bytes_differ():
    a, b = "a" * 80, "a" * 79 + "b"
    assert not verify_password(b, hash_password(a))


def test_legacy_bcrypt_hashes_still_verify_and_need_rehash():
    old = _old_hash(PW)
    assert old.startswith("$2b$")
    assert verify_password(PW, old)
    assert not verify_password("wrong", old)
    assert password_needs_rehash(old)


def test_argon2_with_weaker_parameters_needs_rehash():
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PW)
    assert verify_password(PW, weak)
    assert password_needs_rehash(weak)


@pytest.mark.parametrize("stored", ["!", "", "plaintext", "$argon2id$garbage", "$2b$garbage"])
def test_sentinels_and_junk_never_verify_or_rehash(stored):
    # "!" is the seeded system user (migration 0017).
    assert not verify_password("!", stored)
    assert not verify_password(PW, stored)
    assert not verify_login_password(PW, stored)
    if stored in ("!", "", "plaintext"):
        assert not password_needs_rehash(stored)


def test_login_check_accepts_both_kinds_and_rejects_unknown_users():
    assert verify_login_password(PW, hash_password(PW))
    assert verify_login_password(PW, _old_hash(PW))
    assert not verify_login_password("wrong", hash_password(PW))
    assert not verify_login_password("wrong", _old_hash(PW))
    assert not verify_login_password(PW, None)


def test_login_check_runs_both_hashers_for_every_account(monkeypatch):
    # Equal work for an unknown user, an argon2 user and a bcrypt user, so the
    # response time does not reveal which usernames exist.
    calls: list[str] = []
    real_argon2, real_bcrypt = security._argon2_ok, security._bcrypt_ok
    monkeypatch.setattr(security, "_argon2_ok",
                        lambda p, h: calls.append("argon2") or real_argon2(p, h))
    monkeypatch.setattr(security, "_bcrypt_ok",
                        lambda p, h: calls.append("bcrypt") or real_bcrypt(p, h))
    for stored in (None, hash_password(PW), _old_hash(PW), "!"):
        calls.clear()
        verify_login_password(PW, stored)
        assert sorted(calls) == ["argon2", "bcrypt"], stored
