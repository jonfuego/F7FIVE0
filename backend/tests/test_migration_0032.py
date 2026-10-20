"""Migration 0032 round-trip on a scratch SQLite database.

Verifies that 0032 is the single Alembic head, adds the collections /
collection_items tables plus the new columns on movies and media_files,
and that the downgrade removes them cleanly.
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


def _build_pre_0032(engine) -> None:
    """Schema slice that 0031 left behind (what 0032 will alter)."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id CHAR(36) PRIMARY KEY, username TEXT, display_name TEXT,"
            " password_hash TEXT, role TEXT, is_active INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE movies (id CHAR(36) PRIMARY KEY, title TEXT,"
            " tmdb_id INTEGER, radarr_id INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE media_files (id CHAR(36) PRIMARY KEY, path TEXT NOT NULL,"
            " kind TEXT, ref_id CHAR(36), scan_state TEXT DEFAULT 'ready',"
            " missing_since TIMESTAMP, library_id CHAR(36),"
            " bitrate_kbps INTEGER, height INTEGER, video_codec TEXT)"
        ))


def test_0032_is_in_the_revision_chain():
    cfg = _config("sqlite://")
    script = ScriptDirectory.from_config(cfg)
    # 0033 supersedes 0032 as the head; 0032 is still a valid revision.
    all_revs = {r.revision for r in script.walk_revisions()}
    assert "0032" in all_revs, all_revs


def test_0032_upgrade_then_downgrade_round_trip(tmp_path, monkeypatch):
    from app.config import settings

    db_file = tmp_path / "scratch.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setattr(settings, "database_url", url)

    engine = create_engine(url)
    _build_pre_0032(engine)

    cfg = _config(url)
    command.stamp(cfg, "0031")
    command.upgrade(cfg, "0032")

    insp = inspect(engine)
    tables = set(insp.get_table_names())

    assert "collections" in tables
    coll_cols = {c["name"] for c in insp.get_columns("collections")}
    assert {"id", "name", "kind", "tmdb_collection_id", "is_auto", "created_by"} <= coll_cols

    assert "collection_items" in tables
    item_cols = {c["name"] for c in insp.get_columns("collection_items")}
    assert {"id", "collection_id", "entity_kind", "entity_id", "sort_order"} <= item_cols

    mv_cols = {c["name"] for c in insp.get_columns("movies")}
    assert "tmdb_collection_id" in mv_cols
    assert "tmdb_collection_name" in mv_cols
    assert "tmdb_collection_checked_at" in mv_cols

    mf_cols = {c["name"] for c in insp.get_columns("media_files")}
    assert "is_preferred_version" in mf_cols

    # Insert a collection and an item to verify FK integrity.
    # Provide datetime explicitly: the migration uses DEFAULT now() which SQLite
    # doesn't support, so we supply the timestamp ourselves.
    coll_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    movie_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO collections (id, name, kind, is_auto, created_at, updated_at)"
            " VALUES (:id, 'Test', 'movies', 0, datetime('now'), datetime('now'))"
        ), {"id": coll_id})
        conn.execute(text(
            "INSERT INTO collection_items (id, collection_id, entity_kind, entity_id, sort_order, added_at)"
            " VALUES (:id, :cid, 'movie', :eid, 0, datetime('now'))"
        ), {"id": item_id, "cid": coll_id, "eid": movie_id})

    # Downgrade one step.
    command.downgrade(cfg, "-1")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "collections" not in tables
    assert "collection_items" not in tables

    mv_cols_down = {c["name"] for c in insp.get_columns("movies")}
    assert "tmdb_collection_id" not in mv_cols_down
    assert "tmdb_collection_name" not in mv_cols_down
    assert "tmdb_collection_checked_at" not in mv_cols_down

    mf_cols_down = {c["name"] for c in insp.get_columns("media_files")}
    assert "is_preferred_version" not in mf_cols_down

    engine.dispose()
