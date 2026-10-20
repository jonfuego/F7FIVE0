"""Migration 0033 round-trip on a scratch SQLite database.

Verifies that 0033 is the single Alembic head, creates organizer_journals and
organizer_journal_items tables, and that the downgrade removes them cleanly.
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


def _build_pre_0033(engine) -> None:
    """Schema slice that 0032 left behind (what 0033 builds on)."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id CHAR(36) PRIMARY KEY, username TEXT,"
            " display_name TEXT, password_hash TEXT, role TEXT, is_active INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE libraries (id CHAR(36) PRIMARY KEY, kind TEXT NOT NULL,"
            " name TEXT, settings TEXT, sort_order INTEGER DEFAULT 0,"
            " created_at TIMESTAMP, updated_at TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE media_files (id CHAR(36) PRIMARY KEY, path TEXT NOT NULL,"
            " kind TEXT, ref_id CHAR(36), scan_state TEXT DEFAULT 'ready',"
            " library_id CHAR(36))"
        ))


def test_0033_is_the_single_head():
    cfg = _config("sqlite://")
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    assert heads == ["0033"], heads


def test_0033_upgrade_then_downgrade_round_trip(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    db_file = tmp_path / "scratch.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setattr(app_settings, "database_url", url)

    engine = create_engine(url)
    _build_pre_0033(engine)

    cfg = _config(url)
    command.stamp(cfg, "0032")
    command.upgrade(cfg, "0033")

    insp = inspect(engine)
    tables = set(insp.get_table_names())

    assert "organizer_journals" in tables
    j_cols = {c["name"] for c in insp.get_columns("organizer_journals")}
    assert {"id", "library_id", "state", "started_at", "finished_at",
            "item_count", "error", "created_by", "undo_applied_at"} <= j_cols

    assert "organizer_journal_items" in tables
    i_cols = {c["name"] for c in insp.get_columns("organizer_journal_items")}
    assert {"id", "journal_id", "media_file_id", "item_kind",
            "old_path", "new_path", "old_tags", "new_tags",
            "error", "sort_order"} <= i_cols

    # Insert rows to verify FK integrity
    j_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO organizer_journals"
            " (id, state, started_at, item_count)"
            " VALUES (:id, 'preview', datetime('now'), 0)"
        ), {"id": j_id})
        conn.execute(text(
            "INSERT INTO organizer_journal_items"
            " (id, journal_id, item_kind, old_path, sort_order)"
            " VALUES (:id, :jid, 'rename', '/old/path', 0)"
        ), {"id": item_id, "jid": j_id})

    # Downgrade one step
    command.downgrade(cfg, "-1")

    insp2 = inspect(engine)
    tables2 = set(insp2.get_table_names())
    assert "organizer_journals" not in tables2
    assert "organizer_journal_items" not in tables2

    engine.dispose()
