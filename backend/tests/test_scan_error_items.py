"""1.0.18 review item 6: Admin > Scans says what the errors are.

The folder scan keeps each per-file error (path and short reason, at most
ERROR_ITEMS_CAP) in the library's status entry as `error_items`, and a music
rescan where a known file's track moves into an album / disc / track slot
another track holds no longer fails on uq_tracks_album_disc_track.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select

from app import scheduler
from app.models.media_file import MediaFile
from app.models.music import Track
from app.services import ffprobe, scan_library, scan_status
from tests.test_library_scan import _fake_probe, _touch  # noqa: F401
from tests.test_library_scan import file_db, libs  # noqa: F401  (fixtures are used by name)


def _status(file_db):
    with file_db() as db:
        return scan_status.read(db)


def test_a_probe_failure_is_listed_with_its_path_and_reason(file_db, libs, monkeypatch):
    good = libs["movies"] / "Good (2000)" / "Good (2000).mkv"
    bad = libs["movies"] / "Bad (2001)" / "Bad (2001).mkv"
    _touch(good)
    _touch(bad)
    real = _fake_probe(monkeypatch)  # noqa: F841
    probe = ffprobe.probe

    def probe_but_bad(path, timeout=30.0):
        return None if "Bad (2001)" in path else probe(path, timeout)

    monkeypatch.setattr(ffprobe, "probe", probe_but_bad)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", lambda *_a, **_k: None)

    scheduler._run_folder_scan()

    movies = _status(file_db)["libraries"]["movies"]
    assert movies["errors"] == 1
    assert len(movies["error_items"]) == 1
    item = movies["error_items"][0]
    assert item["path"].endswith(os.path.join("Bad (2001)", "Bad (2001).mkv"))
    assert item["reason"] == scan_library.PROBE_FAILED


def test_a_per_file_music_error_is_listed_and_the_list_is_capped(file_db, libs, monkeypatch):
    from sqlalchemy.exc import DataError

    names = [f"Artist {i:02d}" for i in range(scan_library.ERROR_ITEMS_CAP + 3)]
    for name in names:
        _touch(libs["music"] / name / "Album" / "01 - Song.flac")
    monkeypatch.setattr(scan_library, "read_tags", lambda path: {
        "albumartist": Path(path).parts[-3], "album": "Album", "title": "Song", "tracknumber": "1",
    })
    _fake_probe(monkeypatch)

    def always_fails(db, **kw):
        raise DataError("INSERT INTO x", {}, Exception("value too long for type character varying(64)"))

    monkeypatch.setattr(scan_library, "_upsert_file", always_fails)
    scheduler._run_folder_scan()

    music = _status(file_db)["libraries"]["music"]
    assert music["errors"] == len(names)
    assert len(music["error_items"]) == scan_library.ERROR_ITEMS_CAP
    first = music["error_items"][0]
    assert first["path"].endswith("01 - Song.flac")
    assert "value too long" in first["reason"]
    assert "INSERT INTO" not in first["reason"]


def test_a_track_moving_into_an_occupied_slot_is_linked_not_an_error(file_db, libs, monkeypatch):
    # Two files on one album, numbered 1 and 2. On the rescan the second file is
    # retagged as track 1, the slot the first track holds. Before the fix this
    # broke uq_tracks_album_disc_track (the Tears for Fears error on the VM).
    a = libs["music"] / "Tears for Fears" / "Raoul" / "01 - Raoul.flac"
    b = libs["music"] / "Tears for Fears" / "Raoul" / "02 - Other.flac"
    _touch(a)
    _touch(b)
    numbers = {str(a): "1", str(b): "2"}
    monkeypatch.setattr(scan_library, "read_tags", lambda path: {
        "albumartist": "Tears for Fears", "album": "Raoul and the Kings of Spain",
        "title": Path(path).stem, "tracknumber": numbers[str(path)],
    })
    _fake_probe(monkeypatch)

    scheduler._run_folder_scan()
    assert _status(file_db)["libraries"]["music"]["errors"] == 0

    numbers[str(b)] = "1"
    scheduler._run_folder_scan()

    music = _status(file_db)["libraries"]["music"]
    assert music["errors"] == 0, music.get("error_items")
    assert music["error_items"] == []
    with file_db() as db:
        files = db.scalars(select(MediaFile)).all()
        assert len(files) == 2
        # Both files now sit on the one track that holds album / disc 1 / track 1.
        refs = {mf.ref_id for mf in files}
        assert len(refs) == 1
        track = db.get(Track, refs.pop())
        assert (track.disc_number, track.track_number) == (1, 1)
