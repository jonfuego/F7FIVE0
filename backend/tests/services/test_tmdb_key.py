"""TMDB key: saved (Admin) vs .env, the key check, and reminders."""
from __future__ import annotations

import uuid

import httpx

from app.config import settings
from app.services import reminders, tmdb_key


def _client(status: int) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json={})))


def test_saved_key_wins_over_env(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "envkey")
    assert tmdb_key.get() == "envkey" and tmdb_key.source(db_session) == "env"
    tmdb_key.save(db_session, "  savedkey ")
    assert tmdb_key.get() == "savedkey" and tmdb_key.source(db_session) == "admin"
    tmdb_key.clear(db_session)
    assert tmdb_key.get() == "envkey"
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    assert tmdb_key.get() == "" and tmdb_key.source(db_session) is None


def test_masked():
    assert tmdb_key.masked("abcdef123456").endswith("3456")
    assert "abcdef" not in tmdb_key.masked("abcdef123456")


def test_check():
    assert tmdb_key.check("k", _client(200)).ok
    bad = tmdb_key.check("k", _client(401))
    assert not bad.ok and "rejected" in bad.message
    assert not tmdb_key.check("", _client(200)).ok
    assert "Read Access Token" in tmdb_key.check("eyJhbGciOi", _client(200)).message


def test_reminder_snooze_and_give_up(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    uid = uuid.uuid4()
    assert [r.id for r in reminders.active(db_session, uid)] == ["tmdb_key"]
    reminders.snooze(db_session, uid, "tmdb_key")
    assert reminders.active(db_session, uid) == []
    # After the snooze runs out it comes back, until MAX_SHOWINGS snoozes.
    for _ in range(reminders.MAX_SHOWINGS - 1):
        key = f"reminder:tmdb_key:{uid}"
        from app.services import app_settings
        state = app_settings.get(db_session, key)
        state["snoozed_until"] = "2000-01-01T00:00:00+00:00"
        app_settings.put(db_session, key, state)
        assert [r.id for r in reminders.active(db_session, uid)] == ["tmdb_key"]
        reminders.snooze(db_session, uid, "tmdb_key")
    state = app_settings.get(db_session, f"reminder:tmdb_key:{uid}")
    state["snoozed_until"] = "2000-01-01T00:00:00+00:00"
    app_settings.put(db_session, f"reminder:tmdb_key:{uid}", state)
    assert reminders.active(db_session, uid) == []


def test_reminder_hidden_once_key_set(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    uid = uuid.uuid4()
    tmdb_key.save(db_session, "k")
    assert reminders.active(db_session, uid) == []


def test_reminder_forever(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    uid = uuid.uuid4()
    reminders.snooze(db_session, uid, "tmdb_key", forever=True)
    from app.services import app_settings
    state = app_settings.get(db_session, f"reminder:tmdb_key:{uid}")
    state["snoozed_until"] = "2000-01-01T00:00:00+00:00"
    app_settings.put(db_session, f"reminder:tmdb_key:{uid}", state)
    assert reminders.active(db_session, uid) == []
