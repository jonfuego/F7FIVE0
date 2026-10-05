"""Admin > Library folders endpoints."""
from __future__ import annotations

from app import scheduler


def test_get_and_put_library_folders(client, tmp_path, monkeypatch):
    triggered = []
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda: triggered.append(True))
    present = tmp_path / "movies"
    present.mkdir()
    r = client.get("/api/admin/library-folders")
    assert r.status_code == 200
    assert {lib["kind"] for lib in r.json()["libraries"]} == {"movies", "tv", "music", "music_videos"}

    r = client.put("/api/admin/library-folders", json={"folders": {
        "movies": [str(present), str(tmp_path / "asleep")],
    }})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "admin"
    movies = next(lib for lib in body["libraries"] if lib["kind"] == "movies")
    assert [(f["path"], f["reachable"]) for f in movies["folders"]] == [
        (str(present), True), (str(tmp_path / "asleep"), False),
    ]
    assert triggered == [True]


def test_put_library_folders_rejects_bad_input(client, tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "trigger_folder_scan_now", lambda: None)
    r = client.put("/api/admin/library-folders", json={"folders": {"movies": ["relative"]}})
    assert r.status_code == 400 and "full path" in r.json()["detail"]
    r = client.put("/api/admin/library-folders", json={"folders": {"podcasts": [str(tmp_path)]}})
    assert r.status_code == 400
