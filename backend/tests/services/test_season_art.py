"""Season posters for the season thumbs on the TV show page (review items 20
and 22): folder sidecars, Sonarr season images and TMDB season posters land in
art_overrides as `season` art, and the show detail lists each season with its
poster (null means the web falls back to the show poster)."""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.models.art import ArtOverride, ENTITY_SEASON, ROLE_POSTER
from app.models.tv import Season, Series
from app.services import art as art_service
from app.services import ffprobe, scan_library, season_art


def _png_bytes(color=(200, 100, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), color).save(buf, "PNG")
    return buf.getvalue()


def _png(path: Path, color=(200, 100, 20)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(color))


def _touch(path: Path, size: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


@pytest.fixture()
def fake_probe(monkeypatch):
    def _probe(path, timeout=30.0):
        if not os.path.exists(path):
            return None
        return ffprobe.ProbeResult(
            container="mkv", size_bytes=os.path.getsize(path), duration_sec=120,
            bitrate_kbps=1000, video_codec="h264", audio_codec="aac",
            audio_channels=2, width=1920, height=1080,
        )
    monkeypatch.setattr(ffprobe, "probe", _probe)


@pytest.fixture()
def system_user(db_session):
    from app.models.user import User
    db_session.add(User(id=art_service.SYSTEM_USER_ID, username="system", display_name="System",
                        password_hash="!", role="admin", is_active=False))
    db_session.flush()


@pytest.fixture()
def tv_root(tmp_path, monkeypatch):
    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key", "tmdb_api_key"):
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    for k in ("movies", "tv", "music"):
        (tmp_path / k).mkdir()
        monkeypatch.setattr(settings, f"library_root_{k}", str(tmp_path / k))
    return tmp_path / "tv"


# ---------------------------------------------------------------------------
# Discovery (pure, filesystem only)
# ---------------------------------------------------------------------------
def test_show_folder_names():
    assert season_art.show_folder_stems(1) == ("season01-poster", "season1-poster")
    assert season_art.show_folder_stems(12) == ("season12-poster",)
    assert season_art.show_folder_stems(0)[0] == "season-specials-poster"


def test_find_season_poster_in_the_show_folder(tmp_path):
    show = tmp_path / "Adventure Time"
    _png(show / "Season01-Poster.PNG")
    _png(show / "season2-poster.jpg")
    _png(show / "season-specials-poster.webp")
    _png(show / "poster.jpg")  # the show poster, never a season's
    assert season_art.find_season_poster(str(show), 1).endswith("Season01-Poster.PNG")
    assert season_art.find_season_poster(str(show), 2).endswith("season2-poster.jpg")
    assert season_art.find_season_poster(str(show), 0).endswith("season-specials-poster.webp")
    assert season_art.find_season_poster(str(show), 3, [str(show)]) is None


def test_find_season_poster_inside_the_season_folder(tmp_path):
    show = tmp_path / "Show"
    _png(show / "Season 03" / "folder.jpg")
    assert season_art.find_season_poster(str(show), 3, [str(show / "Season 03")]).endswith("folder.jpg")
    # The show-folder name wins over the one inside the season folder.
    _png(show / "season03-poster.png")
    assert season_art.find_season_poster(str(show), 3, [str(show / "Season 03")]).endswith(
        "season03-poster.png"
    )


def test_find_season_poster_ignores_non_images_and_missing_folders(tmp_path):
    show = tmp_path / "Show"
    _touch(show / "season01-poster.txt")
    assert season_art.find_season_poster(str(show), 1) is None
    assert season_art.find_season_poster(str(tmp_path / "nope"), 1, [str(tmp_path / "gone")]) is None


# ---------------------------------------------------------------------------
# Folder scan
# ---------------------------------------------------------------------------
def _scan_show(tv_root: Path) -> Path:
    show = tv_root / "Adventure Time (2010)"
    _touch(show / "Season 01" / "Adventure Time - S01E01 - Slumber Party Panic.mkv")
    _touch(show / "Season 01" / "Adventure Time - S01E02 - Trouble in Lumpy Space.mkv")
    _touch(show / "Season 02" / "Adventure Time - S02E01 - It Came from the Nightosphere.mkv")
    _touch(show / "Season 03" / "Adventure Time - S03E01 - Conquest of Cuteness.mkv")
    _touch(show / "Specials" / "Adventure Time - S00E01 - Pilot.mkv")
    _png(show / "poster.png")
    _png(show / "season01-poster.png", (10, 20, 200))
    _png(show / "Season 02" / "poster.png", (10, 200, 20))
    _png(show / "season-specials-poster.jpg".replace(".jpg", ".png"), (90, 90, 90))
    return show


def _season(db, series, num):
    return db.scalar(select(Season).where(Season.series_id == series.id, Season.season_number == num))


def test_scan_tv_imports_season_posters(db_session, tv_root, fake_probe, system_user):
    _scan_show(tv_root)
    stats = scan_library.scan_tv(db_session)
    series = db_session.scalar(select(Series))
    for num in (0, 1, 2):
        row = db_session.get(ArtOverride, (ENTITY_SEASON, _season(db_session, series, num).id, ROLE_POSTER))
        assert row is not None and row.source_kind == "local", num
        # Same pipeline as every other picture: the 300 and 600 px copies exist.
        original = Path(settings.art_root) / row.local_path
        assert art_service.copy_path(original, 300).is_file()
        assert art_service.copy_path(original, 600).is_file()
    # Season 3 has no sidecar and there is no TMDB key: no season art.
    assert db_session.get(
        ArtOverride, (ENTITY_SEASON, _season(db_session, series, 3).id, ROLE_POSTER),
    ) is None
    assert stats.art_imported >= 4  # show poster + three seasons

    # A rescan with nothing changed imports nothing again.
    again = scan_library.scan_tv(db_session)
    assert again.art_imported == 0


def test_scan_tv_never_replaces_an_admin_season_poster(db_session, tv_root, fake_probe, system_user):
    show = _scan_show(tv_root)
    scan_library.scan_tv(db_session)
    series = db_session.scalar(select(Series))
    s1 = _season(db_session, series, 1)
    art_service.save_upload_bytes(
        db_session, entity_kind=ENTITY_SEASON, entity_id=s1.id, role=ROLE_POSTER,
        data=_png_bytes((1, 2, 3)), set_by_user_id=art_service.SYSTEM_USER_ID,
        source_kind="upload",
    )
    _png(show / "season01-poster.png", (250, 250, 0))
    scan_library.scan_tv(db_session)
    assert db_session.get(ArtOverride, (ENTITY_SEASON, s1.id, ROLE_POSTER)).source_kind == "upload"


def test_scan_tv_fills_missing_seasons_from_tmdb(db_session, tv_root, fake_probe, system_user, monkeypatch):
    _scan_show(tv_root)
    scan_library.scan_tv(db_session)
    series = db_session.scalar(select(Series))
    series.tmdb_id = 15260
    db_session.flush()

    from app.services import tmdb_key
    from app.services.metadata import tmdb as tmdb_mod
    monkeypatch.setattr(tmdb_key, "get", lambda: "key")
    monkeypatch.setattr(tmdb_mod.TMDBClient, "get_series", lambda self, tid: {
        "id": tid,
        "seasons": [
            {"season_number": 1, "poster_path": "/s1.jpg"},
            {"season_number": 3, "poster_path": "/s3.jpg"},
            {"season_number": 4, "poster_path": "/s4.jpg"},  # not on disk
        ],
    })
    fetched: list[str] = []

    def _fetch(url):
        fetched.append(url)
        return _png_bytes((5, 5, 5))
    monkeypatch.setattr(art_service, "fetch_url_bytes", _fetch)

    scan_library.scan_tv(db_session)
    # Season 1 keeps its sidecar; only season 3 (no picture) takes TMDB.
    assert fetched == ["https://image.tmdb.org/t/p/w780/s3.jpg"]
    s3 = db_session.get(ArtOverride, (ENTITY_SEASON, _season(db_session, series, 3).id, ROLE_POSTER))
    assert s3 is not None and s3.source_kind == "tmdb"
    s1 = db_session.get(ArtOverride, (ENTITY_SEASON, _season(db_session, series, 1).id, ROLE_POSTER))
    assert s1.source_kind == "local"

    # A sidecar added later replaces the TMDB pick.
    _png(tv_root / "Adventure Time (2010)" / "season03-poster.png", (7, 7, 7))
    scan_library.scan_tv(db_session)
    s3 = db_session.get(ArtOverride, (ENTITY_SEASON, _season(db_session, series, 3).id, ROLE_POSTER))
    assert s3.source_kind == "local"


# ---------------------------------------------------------------------------
# Sonarr
# ---------------------------------------------------------------------------
def test_sonarr_season_images(db_session, tv_root, system_user, monkeypatch):
    series = Series(title="Sonarr Show", sonarr_id=7)
    db_session.add(series)
    db_session.flush()
    for n in (1, 2):
        db_session.add(Season(series_id=series.id, season_number=n))
    db_session.flush()
    fetched: list[str] = []

    def _fetch(url):
        fetched.append(url)
        return _png_bytes()
    monkeypatch.setattr(art_service, "fetch_url_bytes", _fetch)

    payload = [
        {"seasonNumber": 1, "images": [{"coverType": "poster", "remoteUrl": "https://img.example/s1.jpg"}]},
        {"seasonNumber": 2, "images": [{"coverType": "banner", "remoteUrl": "https://img.example/b.jpg"}]},
        {"seasonNumber": 5, "images": [{"coverType": "poster", "remoteUrl": "https://img.example/s5.jpg"}]},
    ]
    assert season_art.apply_sonarr_season_posters(db_session, series, payload) == 1
    assert fetched == ["https://img.example/s1.jpg"]
    urls = season_art.season_poster_urls(db_session, series.id)
    assert set(urls) == {1}
    s1 = _season(db_session, series, 1)
    assert urls[1].startswith(f"/api/art/season/{s1.id}/poster?v=")
    # Same URL again: nothing downloaded.
    season_art.apply_sonarr_season_posters(db_session, series, payload)
    assert len(fetched) == 1
    # No seasons in the payload is a no-op.
    assert season_art.apply_sonarr_season_posters(db_session, series, None) == 0


def test_tmdb_season_posters_never_replace_existing_art(db_session, tv_root, system_user, monkeypatch):
    series = Series(title="T", tmdb_id=1)
    db_session.add(series)
    db_session.flush()
    s1 = Season(series_id=series.id, season_number=1)
    db_session.add(s1)
    db_session.flush()
    art_service.save_upload_bytes(
        db_session, entity_kind=ENTITY_SEASON, entity_id=s1.id, role=ROLE_POSTER,
        data=_png_bytes(), set_by_user_id=art_service.SYSTEM_USER_ID, source_kind="sonarr",
    )
    monkeypatch.setattr(art_service, "fetch_url_bytes", lambda url: pytest.fail("no fetch"))
    payload = {"seasons": [{"season_number": 1, "poster_path": "/x.jpg"}]}
    assert season_art.apply_tmdb_season_posters(db_session, series, payload) == 0
    assert season_art.apply_tmdb_season_posters(db_session, series, None) == 0


def test_no_tmdb_key_means_no_lookup(db_session, tv_root, monkeypatch):
    series = Series(title="T", tmdb_id=1)
    db_session.add(series)
    db_session.flush()
    db_session.add(Season(series_id=series.id, season_number=1))
    db_session.flush()
    from app.services.metadata import tmdb as tmdb_mod
    monkeypatch.setattr(tmdb_mod.TMDBClient, "get_series", lambda *a: pytest.fail("no lookup"))
    assert season_art.fill_tmdb_season_posters(db_session, series) == 0


# ---------------------------------------------------------------------------
# API: show detail seasons and the art route
# ---------------------------------------------------------------------------
def test_series_detail_lists_seasons_with_posters(client, db_session, tv_root, fake_probe, system_user):
    _scan_show(tv_root)
    scan_library.scan_tv(db_session)
    db_session.commit()
    series = db_session.scalar(select(Series))

    r = client.get(f"/api/series/{series.id}")
    assert r.status_code == 200, r.text
    seasons = r.json()["seasons"]
    assert [s["season_number"] for s in seasons] == [1, 2, 3, 0]
    assert [s["episode_count"] for s in seasons] == [2, 1, 1, 1]
    by_num = {s["season_number"]: s["poster_path"] for s in seasons}
    assert by_num[3] is None
    for num in (0, 1, 2):
        sid = _season(db_session, series, num).id
        assert by_num[num].startswith(f"/api/art/season/{sid}/poster?v=")


def test_season_poster_is_served_with_size_copies(client, db_session, tv_root, system_user):
    from app.api.art import optional_current_user
    from app.main import app
    from tests.conftest import make_active_session

    user = make_active_session(db_session)[0]
    app.dependency_overrides[optional_current_user] = lambda: user
    series = Series(title="Served")
    db_session.add(series)
    db_session.flush()
    season = Season(series_id=series.id, season_number=1)
    db_session.add(season)
    db_session.flush()
    art_service.save_upload_bytes(
        db_session, entity_kind=ENTITY_SEASON, entity_id=season.id, role=ROLE_POSTER,
        data=_png_bytes(), set_by_user_id=art_service.SYSTEM_USER_ID, source_kind="local",
    )
    db_session.commit()
    r = client.get(f"/api/art/season/{season.id}/poster?w=300")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert client.get(f"/api/art/season/{season.id}/backdrop").status_code == 400



def test_skipped_art_download_never_logs_the_arr_api_key(db_session, caplog, monkeypatch):
    import logging
    import uuid as _uuid

    from app.models.art import ENTITY_SEASON, ROLE_POSTER
    from app.services import art

    def boom(*a, **k):
        raise art.ArtValidationError(
            "upstream returned HTTP 401 for http://sonarr:8989/x.jpg?apikey=SECRET123", status_code=502,
        )

    monkeypatch.setattr(art, "fetch_and_save_url", boom)
    images = [{"coverType": "poster", "url": "/MediaCover/12/season-1.jpg"}]
    with caplog.at_level(logging.WARNING):
        row = art.download_art_on_sync(
            db_session, entity_kind=ENTITY_SEASON, entity_id=_uuid.uuid4(), role=ROLE_POSTER,
            images=images, cover_type="poster", source_kind="sonarr",
            arr_base_url="http://sonarr:8989", arr_api_key="SECRET123",
        )
    assert row is None
    assert "art download skipped" in caplog.text
    assert "source=sonarr status=502" in caplog.text
    assert "SECRET123" not in caplog.text
