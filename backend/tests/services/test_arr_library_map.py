"""Unit tests for the per-library *arr root-folder map."""
from __future__ import annotations

from app.models.library import Library, LibraryKind
from app.services import arr_library_map


def _library(db, name, kind, sort_order=0):
    lib = Library(name=name, kind=kind, sort_order=sort_order)
    db.add(lib)
    db.flush()
    return lib


def test_defaults_to_first_library_of_the_kind(db_session):
    first = _library(db_session, "Movies", LibraryKind.movies, sort_order=0)
    _library(db_session, "Kids Movies", LibraryKind.movies, sort_order=1)
    # No explicit mapping: any movie path resolves to the first movies library.
    assert arr_library_map.default_library_id(db_session, "radarr") == first.id
    assert arr_library_map.library_for(db_session, "radarr", r"N:\Movies\A\A.mkv") == first.id


def test_explicit_root_mapping_wins_over_default(db_session):
    first = _library(db_session, "Movies", LibraryKind.movies, sort_order=0)
    kids = _library(db_session, "Kids Movies", LibraryKind.movies, sort_order=1)
    arr_library_map.set_root_library(db_session, "radarr", r"N:\Kids", kids.id)
    db_session.commit()
    # A file under the mapped root goes to that library; others fall back.
    assert arr_library_map.library_for(db_session, "radarr", r"N:\Kids\Toy Story\x.mkv") == kids.id
    assert arr_library_map.library_for(db_session, "radarr", r"N:\Movies\Heat\x.mkv") == first.id
    # The map is readable and clearable.
    assert arr_library_map.get_map(db_session, "radarr") == {r"n:\kids": str(kids.id)}
    arr_library_map.clear_root(db_session, "radarr", r"N:\Kids")
    db_session.commit()
    assert arr_library_map.library_for(db_session, "radarr", r"N:\Kids\Toy Story\x.mkv") == first.id


def test_sonarr_and_lidarr_use_their_own_kind(db_session):
    tv = _library(db_session, "TV", LibraryKind.tv)
    music = _library(db_session, "Music", LibraryKind.music)
    assert arr_library_map.default_library_id(db_session, "sonarr") == tv.id
    assert arr_library_map.default_library_id(db_session, "lidarr") == music.id
    assert arr_library_map.library_for(db_session, "sonarr", r"X:\TV\Show\s01e01.mkv") == tv.id


def test_no_library_of_kind_returns_none(db_session):
    assert arr_library_map.default_library_id(db_session, "radarr") is None
    assert arr_library_map.library_for(db_session, "radarr", r"N:\Movies\A.mkv") is None
