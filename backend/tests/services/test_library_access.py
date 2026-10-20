"""Unit tests for the central library-access helper (deny-list semantics)."""
from __future__ import annotations

import uuid

from app.models.library import Library, LibraryKind, UserLibraryAccess
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.user import User
from app.services import library_access


def _user(db, role="member"):
    u = User(username=f"u-{uuid.uuid4().hex[:8]}", display_name="U",
             password_hash="x", role=role, is_active=True)
    db.add(u)
    db.flush()
    return u


def _library(db, name, kind=LibraryKind.movies, sort_order=0):
    lib = Library(name=name, kind=kind, sort_order=sort_order)
    db.add(lib)
    db.flush()
    return lib


def _file(db, library_id):
    mf = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(),
                   path=f"/m/{uuid.uuid4().hex}.mkv", library_id=library_id,
                   scan_state=ScanState.ready)
    db.add(mf)
    db.flush()
    return mf


def test_admin_sees_all_libraries(db_session):
    admin = _user(db_session, role="admin")
    a = _library(db_session, "A")
    b = _library(db_session, "B", sort_order=1)
    # Even a hide row does not affect an admin.
    db_session.add(UserLibraryAccess(user_id=admin.id, library_id=b.id))
    db_session.flush()
    assert library_access.visible_library_ids(db_session, admin) == {a.id, b.id}
    assert library_access.hidden_library_ids(db_session, admin) == set()
    assert library_access.can_access_library(db_session, admin, b.id)


def test_member_sees_all_minus_hidden(db_session):
    member = _user(db_session)
    a = _library(db_session, "A")
    b = _library(db_session, "B", sort_order=1)
    db_session.add(UserLibraryAccess(user_id=member.id, library_id=b.id))
    db_session.flush()
    assert library_access.hidden_library_ids(db_session, member) == {b.id}
    assert library_access.visible_library_ids(db_session, member) == {a.id}
    assert library_access.can_access_library(db_session, member, a.id)
    assert not library_access.can_access_library(db_session, member, b.id)
    # The file-level and gateway-level checks agree.
    fa, fb = _file(db_session, a.id), _file(db_session, b.id)
    assert library_access.can_access_media_file(db_session, member, fa)
    assert not library_access.can_access_media_file(db_session, member, fb)
    assert library_access.can_user_access_library(db_session, member.id, a.id)
    assert not library_access.can_user_access_library(db_session, member.id, b.id)


def test_null_library_file_is_visible_to_all(db_session):
    member = _user(db_session)
    b = _library(db_session, "B")
    db_session.add(UserLibraryAccess(user_id=member.id, library_id=b.id))
    db_session.flush()
    null_file = _file(db_session, None)
    assert library_access.can_access_media_file(db_session, member, null_file)
    assert library_access.can_user_access_library(db_session, member.id, None)
    # And the SQL clause treats a null library as visible too.
    assert library_access.can_access_item_files(db_session, member, [null_file])
