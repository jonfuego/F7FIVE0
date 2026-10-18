"""Migration 0030 round-trip on a scratch SQLite database.

Builds the pre-0030 schema (users, the old one-folder-per-row `libraries`, and
`media_files`), stamps it at 0029, runs `alembic upgrade head` (which runs only
0030), checks the new shape, then runs one `downgrade` step and checks the new
objects are gone. Also asserts 0030 is the single Alembic head.

Only 0030 runs against SQLite here: the full 0001..0029 chain uses PostgreSQL-only
DDL (ALTER CONSTRAINT, enum ALTER TYPE) that SQLite cannot replay, so the pre-0030
schema is built directly and the version table stamped at 0029.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
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


def _build_pre_0030(engine) -> None:
    """The slice of the pre-0030 schema that 0030 reads or alters."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id CHAR(36) PRIMARY KEY, username TEXT)"))
        conn.execute(text(
            "CREATE TABLE libraries ("
            " id CHAR(36) PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,"
            " root_path TEXT NOT NULL,"
            " created_at TIMESTAMP, updated_at TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE media_files ("
            " id CHAR(36) PRIMARY KEY, path TEXT NOT NULL)"
        ))
        # Two movie libraries (old per-folder rows) that should collapse to one.
        for i, root in enumerate((r"D:\Movies", r"E:\Movies2")):
            conn.execute(
                text("INSERT INTO libraries (id, name, kind, root_path, created_at) "
                     "VALUES (:id, :name, 'movies', :root, :ca)"),
                {"id": str(uuid.uuid4()), "name": "Movies", "root": root,
                 "ca": f"2026-01-0{i + 1} 00:00:00"},
            )


def test_0030_is_the_single_head():
    cfg = _config("sqlite://")
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    assert heads == ["0030"], heads


def test_0030_upgrade_then_downgrade_round_trip(tmp_path, monkeypatch):
    from app.config import settings

    db_file = tmp_path / "scratch.db"
    url = f"sqlite:///{db_file}"
    # env.py reads settings.database_url for the connection it migrates.
    monkeypatch.setattr(settings, "database_url", url)

    engine = create_engine(url)
    _build_pre_0030(engine)

    cfg = _config(url)
    command.stamp(cfg, "0029")

    # Upgrade head (only 0030 runs).
    command.upgrade(cfg, "head")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "library_folders" in tables
    assert "user_library_access" in tables
    lib_cols = {c["name"] for c in insp.get_columns("libraries")}
    assert {"sort_order", "settings"} <= lib_cols
    mf_cols = {c["name"] for c in insp.get_columns("media_files")}
    assert "library_id" in mf_cols

    with engine.connect() as conn:
        # The two movie rows collapsed to one named library...
        libs = conn.execute(text("SELECT id, name, root_path FROM libraries WHERE kind='movies'")).all()
        assert len(libs) == 1
        assert libs[0].name == "Movies"
        assert libs[0].root_path is None
        # ...and both old folders moved into library_folders under it.
        folders = conn.execute(text("SELECT path FROM library_folders")).all()
        assert {f.path for f in folders} == {r"D:\Movies", r"E:\Movies2"}

    # One downgrade step drops the new objects.
    command.downgrade(cfg, "-1")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "library_folders" not in tables
    assert "user_library_access" not in tables
    mf_cols = {c["name"] for c in insp.get_columns("media_files")}
    assert "library_id" not in mf_cols
    lib_cols = {c["name"] for c in insp.get_columns("libraries")}
    assert "sort_order" not in lib_cols
    assert "settings" not in lib_cols

    engine.dispose()
