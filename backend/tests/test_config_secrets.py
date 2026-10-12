"""Production refuses to start on a placeholder, short, empty or shared signing
secret; development and tests only warn."""
from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from app.config import MIN_SECRET_LENGTH, Settings, secret_problems

GOOD_A = "A" * 10 + "bcdefghij" * 4  # 46 chars
GOOD_B = "Z" * 10 + "qrstuvwxy" * 4


def _make(environment: str, jwt: str, hmac: str) -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,
        database_url="sqlite:///:memory:",
        jwt_secret=jwt,
        stream_hmac_secret=hmac,
    )


def test_production_accepts_two_strong_distinct_secrets():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s = _make("production", GOOD_A, GOOD_B)
    assert s.jwt_secret == GOOD_A


@pytest.mark.parametrize("jwt, hmac, expect", [
    ("", GOOD_B, "JWT_SECRET is empty"),
    ("   ", GOOD_B, "JWT_SECRET is empty"),
    (GOOD_A, "", "STREAM_HMAC_SECRET is empty"),
    ("CHANGE_ME", GOOD_B, "JWT_SECRET still holds the CHANGE_ME placeholder"),
    (GOOD_A, "CHANGE_ME_TOO", "STREAM_HMAC_SECRET still holds the CHANGE_ME placeholder"),
    (GOOD_A, "x" * 20 + "change_me" + "y" * 20, "STREAM_HMAC_SECRET still holds the CHANGE_ME placeholder"),
    ("short-secret", GOOD_B, "JWT_SECRET is shorter than 32 characters"),
    (GOOD_A, "k" * (MIN_SECRET_LENGTH - 1), "STREAM_HMAC_SECRET is shorter than 32 characters"),
    (GOOD_A, GOOD_A, "JWT_SECRET and STREAM_HMAC_SECRET are the same value"),
])
def test_production_refuses_each_weak_secret(jwt, hmac, expect):
    with pytest.raises(ValidationError) as ei:
        _make("production", jwt, hmac)
    text = str(ei.value)
    assert "Refusing to start in production" in text
    assert expect in text
    assert "secrets.token_urlsafe(64)" in text  # how to fix it


def test_refusal_names_every_problem_and_never_echoes_a_secret():
    with pytest.raises(ValidationError) as ei:
        _make("production", "CHANGE_ME", "CHANGE_ME")
    text = str(ei.value)
    assert "JWT_SECRET still holds" in text and "STREAM_HMAC_SECRET still holds" in text
    assert "same value" in text
    leaky = "my-very-short-real-secret"
    with pytest.raises(ValidationError) as ei:
        _make("production", leaky, GOOD_B)
    assert leaky not in str(ei.value)


def test_exactly_32_characters_is_enough():
    s = _make("production", "a" * 32, "b" * 32)
    assert len(s.jwt_secret) == 32


def test_production_is_matched_without_case_or_padding():
    with pytest.raises(ValidationError):
        _make(" Production ", "short", GOOD_B)


@pytest.mark.parametrize("environment", ["development", "test", "staging", ""])
def test_other_environments_only_warn(environment):
    with pytest.warns(UserWarning, match="Weak signing secrets") as rec:
        s = _make(environment, "CHANGE_ME", "CHANGE_ME")
    assert s.jwt_secret == "CHANGE_ME"
    msg = str(rec[0].message)
    assert "JWT_SECRET still holds" in msg and "same value" in msg


def test_development_with_strong_secrets_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _make("development", GOOD_A, GOOD_B)


def test_secret_problems_lists_nothing_for_good_secrets():
    assert secret_problems(GOOD_A, GOOD_B) == []


def test_example_env_ships_no_placeholder_secrets():
    from pathlib import Path

    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    values = {}
    for line in example.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    assert values["JWT_SECRET"] == "" and values["STREAM_HMAC_SECRET"] == ""
    assert values["STREAM_URL_TTL_HOURS"] == "4"
    assert Settings.model_fields["stream_url_ttl_hours"].default == 4
