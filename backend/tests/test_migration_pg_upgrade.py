"""Upgrade from 0029 to head on PostgreSQL, with real rows in the tables the
data steps read.

The 0030 to 0033 SQLite tests build a slice of the schema by hand with CHAR
ids, so they could not show that 0030 and 0031 bound their ids as varchar:
PostgreSQL refuses a varchar for a uuid column and has no `uuid = varchar`
operator. 1.0.17 failed on the first install that had library rows. This test
runs the real migration chain on PostgreSQL.

Opt-in, like test_pg_concurrency.py. Point F7FIVE0_PG_TEST_URL at a scratch
PostgreSQL database (the user needs CREATEDB), for example:

    $env:F7FIVE0_PG_TEST_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/f7five0_sectest"
    cd backend; python -m pytest tests/test_migration_pg_upgrade.py -q

The test never touches that database's tables: it creates its own database
next to it (`<name>_migup_<random>`), migrates that one and drops it after. A
URL whose database is named exactly `f7five0` is refused.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PG_URL = os.environ.get("F7FIVE0_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="opt-in: set F7FIVE0_PG_TEST_URL to a scratch PostgreSQL database (see the module docstring)",
)

_BACKEND = Path(__file__).resolve().parent.parent
_ALEMBIC_DIR = _BACKEND / "alembic"


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def scratch_url():
    url = make_url(PG_URL)
    assert url.drivername.startswith("postgresql"), "F7FIVE0_PG_TEST_URL must be a PostgreSQL URL"
    if (url.database or "").lower() == "f7five0":
        pytest.fail("refusing to run the migration test against the f7five0 database")
    name = f"{url.database}_migup_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()


def _seed_0029(conn) -> dict:
    """Rows shaped like a real 1.0.16 install: per-folder library rows, a movie
    with a watch, a track with a play, an episode with a watch, a missing file."""
    ids = {k: str(uuid.uuid4()) for k in (
        "user", "lib_movies_a", "lib_movies_b", "lib_tv",
        "movie", "mf_movie", "wh_movie",
        "artist", "album", "track", "mf_track", "tp",
        "series", "episode", "mf_episode", "wh_episode", "mf_missing",
    )}

    def ins(sql: str, **params) -> None:
        conn.execute(text(sql), params)

    ins("INSERT INTO users (id, username, password_hash, display_name) "
        "VALUES (CAST(:id AS uuid), 'migup', 'x', 'Migration test')", id=ids["user"])
    # Two movie folders (the old one-row-per-folder libraries) and one TV folder.
    ins("INSERT INTO libraries (id, name, kind, root_path, created_at) VALUES "
        "(CAST(:a AS uuid), 'Movies', 'movies', 'D:\\Movies', '2026-01-01T00:00:00Z'), "
        "(CAST(:b AS uuid), 'Movies 2', 'movies', 'E:\\Movies2', '2026-01-02T00:00:00Z'), "
        "(CAST(:t AS uuid), 'TV', 'tv', 'D:\\TV', '2026-01-01T00:00:00Z')",
        a=ids["lib_movies_a"], b=ids["lib_movies_b"], t=ids["lib_tv"])

    ins("INSERT INTO movies (id, title, tmdb_id) VALUES (CAST(:id AS uuid), 'The Matrix', 603)", id=ids["movie"])
    ins("INSERT INTO media_files (id, kind, ref_id, path, scan_state) VALUES "
        "(CAST(:id AS uuid), 'movie', CAST(:ref AS uuid), 'D:\\Movies\\The Matrix (1999).mkv', 'ready')",
        id=ids["mf_movie"], ref=ids["movie"])
    ins("INSERT INTO watch_history (id, user_id, media_file_id, started_at) VALUES "
        "(CAST(:id AS uuid), CAST(:u AS uuid), CAST(:mf AS uuid), now())",
        id=ids["wh_movie"], u=ids["user"], mf=ids["mf_movie"])

    ins("INSERT INTO artists (id, name) VALUES (CAST(:id AS uuid), 'Massive Attack')", id=ids["artist"])
    ins("INSERT INTO albums (id, artist_id, title) VALUES (CAST(:id AS uuid), CAST(:ar AS uuid), 'Mezzanine')",
        id=ids["album"], ar=ids["artist"])
    ins("INSERT INTO tracks (id, album_id, title, mbid) VALUES "
        "(CAST(:id AS uuid), CAST(:al AS uuid), 'Teardrop', 'aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb')",
        id=ids["track"], al=ids["album"])
    ins("INSERT INTO media_files (id, kind, ref_id, path, scan_state) VALUES "
        "(CAST(:id AS uuid), 'track', CAST(:ref AS uuid), 'D:\\Music\\Teardrop.flac', 'ready')",
        id=ids["mf_track"], ref=ids["track"])
    ins("INSERT INTO track_plays (id, user_id, track_id, ms_played) VALUES "
        "(CAST(:id AS uuid), CAST(:u AS uuid), CAST(:t AS uuid), 1000)",
        id=ids["tp"], u=ids["user"], t=ids["track"])

    ins("INSERT INTO series (id, title, tvdb_id) VALUES (CAST(:id AS uuid), 'Severance', 371980)", id=ids["series"])
    ins("INSERT INTO episodes (id, series_id, season_number, episode_number) VALUES "
        "(CAST(:id AS uuid), CAST(:s AS uuid), 1, 2)", id=ids["episode"], s=ids["series"])
    ins("INSERT INTO media_files (id, kind, ref_id, path, scan_state) VALUES "
        "(CAST(:id AS uuid), 'episode', CAST(:ref AS uuid), 'D:\\TV\\Severance S01E02.mkv', 'ready')",
        id=ids["mf_episode"], ref=ids["episode"])
    ins("INSERT INTO watch_history (id, user_id, media_file_id, started_at) VALUES "
        "(CAST(:id AS uuid), CAST(:u AS uuid), CAST(:mf AS uuid), now())",
        id=ids["wh_episode"], u=ids["user"], mf=ids["mf_episode"])

    ins("INSERT INTO media_files (id, kind, ref_id, path, scan_state) VALUES "
        "(CAST(:id AS uuid), 'movie', CAST(:ref AS uuid), 'D:\\Movies\\gone.mkv', 'missing')",
        id=ids["mf_missing"], ref=ids["movie"])
    return ids


def test_upgrade_0029_to_head_with_real_rows(scratch_url, monkeypatch):
    from app.config import settings

    # env.py reads settings.database_url for the connection it migrates.
    monkeypatch.setattr(settings, "database_url", scratch_url)
    cfg = _config(scratch_url)
    command.upgrade(cfg, "0029")

    engine = create_engine(scratch_url)
    try:
        with engine.begin() as conn:
            ids = _seed_0029(conn)

        command.upgrade(cfg, "head")

        head = ScriptDirectory.from_config(cfg).get_current_head()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head

            # One library per kind, holding every old folder of that kind.
            libs = conn.execute(text(
                "SELECT id::text AS id, name, kind::text AS kind, root_path FROM libraries ORDER BY kind"
            )).all()
            assert [(r.kind, r.name) for r in libs] == [("movies", "Movies"), ("tv", "TV")]
            assert all(r.root_path is None for r in libs)
            by_kind = {r.kind: r.id for r in libs}
            assert by_kind["movies"] == ids["lib_movies_a"], "the oldest row of a kind is the one kept"
            assert ids["lib_movies_b"] not in {r.id for r in libs}, "the extra movies row is gone"

            folders = conn.execute(text(
                "SELECT library_id::text AS library_id, path FROM library_folders"
            )).all()
            assert {(f.library_id, f.path) for f in folders} == {
                (by_kind["movies"], "D:\\Movies"),
                (by_kind["movies"], "E:\\Movies2"),
                (by_kind["tv"], "D:\\TV"),
            }

            # watch_history rows are filled for relinking.
            wh = {r.id: r for r in conn.execute(text(
                "SELECT id::text AS id, ref_kind, ref_id::text AS ref_id, last_path, ref_key FROM watch_history"
            ))}
            movie = wh[ids["wh_movie"]]
            assert movie.ref_kind == "movie"
            assert movie.ref_id == ids["mf_movie"]
            assert movie.last_path == "D:\\Movies\\The Matrix (1999).mkv"
            assert movie.ref_key == "tmdb:603"
            episode = wh[ids["wh_episode"]]
            assert episode.ref_kind == "episode"
            assert episode.ref_key == "tvdb:371980:s1e2"

            tp = conn.execute(text(
                "SELECT last_path, ref_key FROM track_plays WHERE id = CAST(:id AS uuid)"
            ), {"id": ids["tp"]}).one()
            assert tp.last_path == "D:\\Music\\Teardrop.flac"
            assert tp.ref_key == "mbrec:aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"

            missing = dict(conn.execute(text(
                "SELECT id::text, missing_since IS NOT NULL FROM media_files"
            )).all())
            assert missing[ids["mf_missing"]] is True
            assert missing[ids["mf_movie"]] is False
    finally:
        engine.dispose()
