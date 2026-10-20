"""Per-library organizer settings stored in Library.settings (nullable Text/JSON).

Shape of the stored JSON:
{
  "ownership": "f7five0" | "arr",
  "naming_template": {"movie": "...", "tv": "...", "music": "..."},
  "tag_profile": {"id3_version": "2.3", "embed_art": false, "mb_ids": false, "strip_unmanaged": false},
  "recycle_folder": ".f7five0-recycle"
}

Defaults:
  ownership: "arr" when arr_managed(kind), else "f7five0"
  recycle_folder: ".f7five0-recycle"
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.library import Library
from app.services.library_folders import arr_managed


def _parse(library: Library) -> dict:
    if not library.settings:
        return {}
    try:
        return json.loads(library.settings)
    except (ValueError, TypeError):
        return {}


def get_settings(db: Session, library_id: uuid.UUID) -> dict:
    lib = db.get(Library, library_id)
    if lib is None:
        return {}
    return _parse(lib)


def save_settings(db: Session, library_id: uuid.UUID, settings_dict: dict) -> None:
    lib = db.get(Library, library_id)
    if lib is None:
        return
    lib.settings = json.dumps(settings_dict)
    db.flush()


def get_ownership(db: Session, library_id: uuid.UUID) -> str:
    lib = db.get(Library, library_id)
    if lib is None:
        return "f7five0"
    s = _parse(lib)
    if "ownership" in s:
        return s["ownership"]
    return "arr" if arr_managed(lib.kind.value) else "f7five0"


def set_ownership(db: Session, library_id: uuid.UUID, value: str) -> None:
    lib = db.get(Library, library_id)
    if lib is None:
        return
    s = _parse(lib)
    s["ownership"] = value
    lib.settings = json.dumps(s)
    db.flush()
