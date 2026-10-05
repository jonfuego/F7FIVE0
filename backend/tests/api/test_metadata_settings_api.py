"""Admin > Metadata (TMDB key) and the reminders banner endpoints."""
from __future__ import annotations

from app import scheduler
from app.config import settings
from app.models.movie import Movie
from app.services import tmdb_key


def _patch(monkeypatch, ok: bool = True):
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    monkeypatch.setattr(tmdb_key, "check", lambda key, client=None: tmdb_key.KeyCheck(ok, "TMDB accepted the key." if ok else "TMDB rejected that key."))
    calls = {"sync": 0, "enrich": []}
    monkeypatch.setattr(scheduler, "trigger_full_sync_now", lambda: calls.__setitem__("sync", calls["sync"] + 1))
    monkeypatch.setattr(scheduler, "schedule_enrich_movie", lambda mid: calls["enrich"].append(mid))
    return calls


def test_save_and_remove_key(client, db_session, monkeypatch):
    calls = _patch(monkeypatch)
    stale = Movie(title="Heat", year=1995, tmdb_id=949, metadata_status="no_external_id")
    db_session.add(stale)
    db_session.flush()

    r = client.get("/api/admin/metadata")
    assert r.status_code == 200 and r.json()["tmdb"] == {"configured": False, "source": None, "masked": None}
    assert [x["id"] for x in client.get("/api/admin/reminders").json()] == ["tmdb_key"]

    r = client.put("/api/admin/metadata/tmdb", json={"api_key": "0123456789abcdef"})
    assert r.status_code == 200, r.text
    tmdb = r.json()["tmdb"]
    assert tmdb["configured"] and tmdb["source"] == "admin" and tmdb["masked"].endswith("cdef")
    assert calls["sync"] == 1 and calls["enrich"] == [stale.id]
    assert client.get("/api/admin/reminders").json() == []

    r = client.delete("/api/admin/metadata/tmdb")
    assert r.status_code == 200 and r.json()["tmdb"]["configured"] is False


def test_bad_key_is_not_saved(client, monkeypatch):
    _patch(monkeypatch, ok=False)
    r = client.put("/api/admin/metadata/tmdb", json={"api_key": "nope"})
    assert r.status_code == 400 and "rejected" in r.json()["detail"]
    assert client.get("/api/admin/metadata").json()["tmdb"]["configured"] is False
    r = client.post("/api/admin/metadata/tmdb/test", json={"api_key": "nope"})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_snooze_reminder(client, monkeypatch):
    _patch(monkeypatch)
    assert client.post("/api/admin/reminders/tmdb_key/snooze", json={}).status_code == 204
    assert client.get("/api/admin/reminders").json() == []
    assert client.post("/api/admin/reminders/nope/snooze", json={}).status_code == 404
