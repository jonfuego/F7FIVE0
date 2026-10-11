"""Radarr / Sonarr / Lidarr settings: saved (Admin) vs .env, clear, no restart."""
from __future__ import annotations

from app.config import settings
from app.services import arr_settings, library_folders, scan_library


def _blank_env(monkeypatch):
    for app in arr_settings.APPS:
        monkeypatch.setattr(settings, f"{app}_api_key", "")
    monkeypatch.setattr(settings, "radarr_url", "http://127.0.0.1:7878")
    monkeypatch.setattr(settings, "radarr_quality_profile_id", 0)
    monkeypatch.setattr(settings, "radarr_root_folder", "")
    monkeypatch.setattr(settings, "arr_webhook_secret", "")


def test_env_only_behaves_as_before(db_session, monkeypatch):
    _blank_env(monkeypatch)
    assert not arr_settings.configured("radarr")
    assert arr_settings.creds("radarr") == ("http://127.0.0.1:7878", "")
    monkeypatch.setattr(settings, "radarr_api_key", "envkey")
    monkeypatch.setattr(settings, "radarr_url", "http://nas:7878/")
    monkeypatch.setattr(settings, "radarr_quality_profile_id", 4)
    monkeypatch.setattr(settings, "radarr_root_folder", "D:\\Movies")
    assert arr_settings.creds("radarr") == ("http://nas:7878", "envkey")
    assert arr_settings.quality_profile_id("radarr") == 4
    assert arr_settings.root_folder("radarr") == "D:\\Movies"
    assert arr_settings.key_source(db_session, "radarr") == "env"


def test_saved_wins_over_env_and_clear_falls_back(db_session, monkeypatch):
    _blank_env(monkeypatch)
    monkeypatch.setattr(settings, "radarr_api_key", "envkey")
    arr_settings.save(db_session, "radarr", url="http://saved:7878/", api_key="  savedkey ",
                      quality_profile_id=7, root_folder="E:\\Films")
    assert arr_settings.creds("radarr") == ("http://saved:7878", "savedkey")
    assert arr_settings.quality_profile_id("radarr") == 7
    assert arr_settings.root_folder("radarr") == "E:\\Films"
    assert arr_settings.key_source(db_session, "radarr") == "admin"

    arr_settings.clear_key(db_session, "radarr")
    assert arr_settings.api_key("radarr") == "envkey"          # .env applies again
    assert arr_settings.url("radarr") == "http://saved:7878"   # the rest stays saved
    arr_settings.clear(db_session, "radarr")
    assert arr_settings.creds("radarr") == ("http://127.0.0.1:7878", "envkey")
    assert arr_settings.quality_profile_id("radarr") == 0


def test_blank_saved_value_means_use_env(db_session, monkeypatch):
    _blank_env(monkeypatch)
    monkeypatch.setattr(settings, "radarr_api_key", "envkey")
    monkeypatch.setattr(settings, "radarr_root_folder", "D:\\Movies")
    arr_settings.save(db_session, "radarr", api_key="savedkey", root_folder="E:\\Films")
    # A blank key box leaves the saved key alone; a blank root folder removes the saved one.
    arr_settings.save(db_session, "radarr", api_key="", root_folder="")
    assert arr_settings.api_key("radarr") == "savedkey"
    assert arr_settings.root_folder("radarr") == "D:\\Movies"


def test_saving_takes_effect_without_a_restart(db_session, monkeypatch):
    """Cached per process, replaced on save: no wait for the cache to expire."""
    _blank_env(monkeypatch)
    assert not arr_settings.configured("sonarr")
    arr_settings.save(db_session, "sonarr", api_key="k")
    assert arr_settings.configured("sonarr")
    arr_settings.clear_key(db_session, "sonarr")
    assert not arr_settings.configured("sonarr")


def test_a_cold_cache_reads_what_was_committed(db_session, monkeypatch):
    _blank_env(monkeypatch)
    arr_settings.save(db_session, "lidarr", api_key="k")
    db_session.commit()
    arr_settings.reset_cache()  # a fresh process
    assert arr_settings.configured("lidarr")


def test_key_moves_the_library_between_scan_and_arr(db_session, monkeypatch, tmp_path):
    _blank_env(monkeypatch)
    monkeypatch.setattr(settings, "library_root_movies", str(tmp_path))
    assert scan_library.movies_enabled() and not library_folders.arr_managed("movies")
    arr_settings.save(db_session, "radarr", api_key="k")
    assert not scan_library.movies_enabled() and library_folders.arr_managed("movies")
    arr_settings.clear_key(db_session, "radarr")
    assert scan_library.movies_enabled() and not library_folders.arr_managed("movies")


def test_webhook_secret_saved_wins(db_session, monkeypatch):
    _blank_env(monkeypatch)
    assert arr_settings.webhook_secret() == "" and arr_settings.webhook_source(db_session) is None
    monkeypatch.setattr(settings, "arr_webhook_secret", "envsecret")
    assert arr_settings.webhook_secret() == "envsecret" and arr_settings.webhook_source(db_session) == "env"
    arr_settings.save_webhook_secret(db_session, " savedsecret ")
    assert arr_settings.webhook_secret() == "savedsecret" and arr_settings.webhook_source(db_session) == "admin"
    arr_settings.clear_webhook_secret(db_session)
    assert arr_settings.webhook_secret() == "envsecret"


def test_new_webhook_secret_is_long_and_url_safe():
    a, b = arr_settings.new_webhook_secret(), arr_settings.new_webhook_secret()
    assert a != b and len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_masked_never_shows_the_whole_key():
    assert arr_settings.masked("abcdef123456").endswith("3456")
    assert "abcdef" not in arr_settings.masked("abcdef123456")
