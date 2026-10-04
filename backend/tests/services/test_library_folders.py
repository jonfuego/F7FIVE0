"""Library source folders: parsing, validation, and the env / DB switch."""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import library_folders as lf


def test_parse_splits_and_dedupes():
    assert lf.parse(r' D:\Movies ; \\nas\media\Movies;;d:\movies\ ') == [r"D:\Movies", r"\\nas\media\Movies"]
    assert lf.parse("") == [] and lf.parse(None) == []
    assert lf.parse('"E:\\Films"') == ["E:\\Films"]


def test_env_folders(monkeypatch):
    monkeypatch.setattr(settings, "library_root_movies", r"D:\Movies;E:\Movies")
    assert lf.folders(None, "movies") == [r"D:\Movies", r"E:\Movies"]


@pytest.mark.parametrize("folders,needle", [
    ({"movies": ["Movies"]}, "not a full path"),
    ({"movies": [r"D:\Media"], "tv": [r"D:\Media\TV"]}, "inside"),
    ({"movies": [r"D:\Movies", r"D:\Movies\4K"]}, "inside"),
    ({"movies": [r"D:\Movies"], "music": [r"d:\movies"]}, "inside"),
    ({"movies": "D:\\Movies"}, "expected a list"),
])
def test_validate_rejects(folders, needle):
    with pytest.raises(lf.FolderError) as exc:
        lf.validate(folders)
    assert needle in str(exc.value)


def test_validate_rejects_own_data_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "art_root", tmp_path / "data" / "art")
    with pytest.raises(lf.FolderError):
        lf.validate({"movies": [str(tmp_path / "data")]})


def test_validate_accepts_unc_and_drive():
    clean = lf.validate({"movies": [r"D:\Movies", r"\\nas\media\Movies"], "tv": [r"E:\TV"]})
    assert clean["movies"] == [r"D:\Movies", r"\\nas\media\Movies"]
    assert clean["music"] == [] and clean["music_videos"] == []


def test_save_switches_source_and_keeps_order(db_session, monkeypatch):
    monkeypatch.setattr(settings, "library_root_tv", r"T:\TV")
    assert lf.source(db_session) == "env"
    lf.save(db_session, {"movies": [r"Z:\B", r"Y:\A"], "music": [r"M:\Music"]})
    assert lf.source(db_session) == "admin"
    assert lf.folders(db_session, "movies") == [r"Z:\B", r"Y:\A"]
    # Saved set is authoritative: TV is now unconfigured.
    assert lf.folders(db_session, "tv") == []
    lf.save(db_session, {"movies": [r"Y:\A"]})
    assert lf.folders(db_session, "movies") == [r"Y:\A"] and lf.folders(db_session, "music") == []


def test_removing_a_folder_hides_its_files(db_session, monkeypatch):
    import uuid
    from app.models.media_file import MediaFile, MediaKind, ScanState
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    lf.save(db_session, {"movies": [r"D:\Movies", r"E:\Movies"]})
    a = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(), path=r"D:\Movies\Heat.mkv", scan_state=ScanState.ready)
    b = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(), path=r"E:\Movies\Alien.mkv", scan_state=ScanState.ready)
    db_session.add_all([a, b])
    db_session.flush()
    lf.save(db_session, {"movies": [r"D:\Movies"]})
    assert a.scan_state == ScanState.ready and b.scan_state == ScanState.missing


def test_removing_a_folder_leaves_arr_libraries_alone(db_session, monkeypatch):
    import uuid
    from app.models.media_file import MediaFile, MediaKind, ScanState
    monkeypatch.setattr(settings, "radarr_api_key", "x")
    lf.save(db_session, {"movies": [r"E:\Movies"]})
    b = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(), path=r"E:\Movies\Alien.mkv", scan_state=ScanState.ready)
    db_session.add(b)
    db_session.flush()
    lf.save(db_session, {"movies": []})
    assert b.scan_state == ScanState.ready
