"""Migration 0031 round-trip on a scratch SQLite database.

Builds the post-0030 schema that 0031 alters (watch_history, track_plays,
media_files, plus the lookup tables the backfill queries), stamps at 0030,
runs upgrade 0031, checks structural changes and the backfill, then runs one
downgrade step and checks the objects are gone. Also asserts 0031 is the single
Alembic head.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

_BACKEND = Path(__file__).resolve().parent.parent
_ALEMBIC_DIR = _BACKEND / "alembic"


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _build_pre_0031(engine) -> None:
    """The slice of the pre-0031 schema that 0031 reads or alters."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE media_files ("
            " id CHAR(36) PRIMARY KEY, path TEXT NOT NULL,"
            " kind TEXT, ref_id CHAR(36), scan_state TEXT DEFAULT 'ready')"
        ))
        conn.execute(text(
            "CREATE TABLE watch_history ("
            " id CHAR(36) PRIMARY KEY,"
            " media_file_id CHAR(36) NOT NULL,"
            " user_id CHAR(36), watched_at TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE track_plays ("
            " id CHAR(36) PRIMARY KEY,"
            " track_id CHAR(36) NOT NULL,"
            " user_id CHAR(36), played_at TIMESTAMP)"
        ))
        # Tables the backfill joins against for ref_key construction.
        conn.execute(text("CREATE TABLE movies (id CHAR(36) PRIMARY KEY, tmdb_id INTEGER)"))
        conn.execute(text("CREATE TABLE tracks (id CHAR(36) PRIMARY KEY, mbid TEXT)"))
        conn.execute(text(
            "CREATE TABLE episodes (id CHAR(36) PRIMARY KEY, series_id CHAR(36),"
            " season_number INTEGER, episode_number INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE series (id CHAR(36) PRIMARY KEY, tvdb_id INTEGER, tmdb_id INTEGER)"
        ))


def _insert_fixtures(conn) -> dict:
    """Insert a movie + track + watch_history + track_play for backfill verification."""
    movie_id = str(uuid.uuid4())
    track_id = str(uuid.uuid4())
    mf_movie_id = str(uuid.uuid4())
    mf_track_id = str(uuid.uuid4())
    wh_id = str(uuid.uuid4())
    tp_id = str(uuid.uuid4())
    wh_id_missing = str(uuid.uuid4())
    mf_missing_id = str(uuid.uuid4())

    conn.execute(text("INSERT INTO movies (id, tmdb_id) VALUES (:id, 42)"), {"id": movie_id})
    conn.execute(text("INSERT INTO tracks (id, mbid) VALUES (:id, 'aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb')"),
                 {"id": track_id})
    conn.execute(text(
        "INSERT INTO media_files (id, path, kind, ref_id, scan_state) VALUES (:id, :p, 'movie', :ref, 'ready')"
    ), {"id": mf_movie_id, "p": r"D:\Movies\foo.mkv", "ref": movie_id})
    conn.execute(text(
        "INSERT INTO media_files (id, path, kind, ref_id, scan_state) VALUES (:id, :p, 'track', :ref, 'ready')"
    ), {"id": mf_track_id, "p": r"D:\Music\bar.flac", "ref": track_id})
    conn.execute(text(
        "INSERT INTO media_files (id, path, kind, ref_id, scan_state) VALUES (:id, :p, 'movie', :ref, 'missing')"
    ), {"id": mf_missing_id, "p": r"D:\Movies\gone.mkv", "ref": movie_id})
    conn.execute(text(
        "INSERT INTO watch_history (id, media_file_id) VALUES (:id, :mfid)"
    ), {"id": wh_id, "mfid": mf_movie_id})
    conn.execute(text(
        "INSERT INTO watch_history (id, media_file_id) VALUES (:id, :mfid)"
    ), {"id": wh_id_missing, "mfid": mf_missing_id})
    conn.execute(text(
        "INSERT INTO track_plays (id, track_id) VALUES (:id, :tid)"
    ), {"id": tp_id, "tid": track_id})
    return {
        "movie_id": movie_id, "track_id": track_id,
        "mf_movie_id": mf_movie_id, "mf_track_id": mf_track_id,
        "mf_missing_id": mf_missing_id,
        "wh_id": wh_id, "wh_id_missing": wh_id_missing, "tp_id": tp_id,
    }


def test_0031_has_a_successor():
    cfg = _config("sqlite://")
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision("0031")
    assert rev is not None
    # 0031 is not the head now that 0032 was added.
    assert "0031" not in script.get_heads()


def test_0031_upgrade_then_downgrade_round_trip(tmp_path, monkeypatch):
    from app.config import settings

    db_file = tmp_path / "scratch.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setattr(settings, "database_url", url)

    engine = create_engine(url)
    _build_pre_0031(engine)

    ids: dict = {}
    with engine.begin() as conn:
        ids = _insert_fixtures(conn)

    cfg = _config(url)
    command.stamp(cfg, "0030")

    # Upgrade one step (0031 only).
    command.upgrade(cfg, "0031")

    insp = inspect(engine)
    tables = set(insp.get_table_names())

    # metadata_locks table was created.
    assert "metadata_locks" in tables
    ml_cols = {c["name"] for c in insp.get_columns("metadata_locks")}
    assert {"id", "entity_kind", "entity_id", "field_name", "locked_at"} <= ml_cols

    # watch_history gained ref columns.
    wh_cols = {c["name"] for c in insp.get_columns("watch_history")}
    assert {"ref_kind", "ref_id", "last_path", "ref_key"} <= wh_cols

    # track_plays gained last_path and ref_key.
    tp_cols = {c["name"] for c in insp.get_columns("track_plays")}
    assert {"last_path", "ref_key"} <= tp_cols

    # media_files gained missing_since.
    mf_cols = {c["name"] for c in insp.get_columns("media_files")}
    assert "missing_since" in mf_cols

    with engine.connect() as conn:
        # Backfill: watch_history row should have ref_kind and last_path.
        wh = conn.execute(
            text("SELECT ref_kind, last_path, ref_key FROM watch_history WHERE id = :id"),
            {"id": ids["wh_id"]},
        ).first()
        assert wh is not None
        assert wh.ref_kind == "movie"
        assert wh.last_path == r"D:\Movies\foo.mkv"
        assert wh.ref_key == "tmdb:42"

        # Backfill: track_plays row should have last_path and ref_key.
        tp = conn.execute(
            text("SELECT last_path, ref_key FROM track_plays WHERE id = :id"),
            {"id": ids["tp_id"]},
        ).first()
        assert tp is not None
        assert tp.last_path == r"D:\Music\bar.flac"
        assert tp.ref_key == "mbrec:aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"

        # Backfill: missing media_file got missing_since set.
        mf_miss = conn.execute(
            text("SELECT missing_since FROM media_files WHERE id = :id"),
            {"id": ids["mf_missing_id"]},
        ).first()
        assert mf_miss is not None
        assert mf_miss.missing_since is not None

        # Non-missing file has no missing_since.
        mf_ok = conn.execute(
            text("SELECT missing_since FROM media_files WHERE id = :id"),
            {"id": ids["mf_movie_id"]},
        ).first()
        assert mf_ok is not None
        assert mf_ok.missing_since is None

    # One downgrade step removes the new objects.
    command.downgrade(cfg, "-1")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "metadata_locks" not in tables

    wh_cols = {c["name"] for c in insp.get_columns("watch_history")}
    assert "ref_kind" not in wh_cols
    assert "ref_id" not in wh_cols
    assert "last_path" not in wh_cols
    assert "ref_key" not in wh_cols

    tp_cols = {c["name"] for c in insp.get_columns("track_plays")}
    assert "last_path" not in tp_cols
    assert "ref_key" not in tp_cols

    mf_cols = {c["name"] for c in insp.get_columns("media_files")}
    assert "missing_since" not in mf_cols

    engine.dispose()
