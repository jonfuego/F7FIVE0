"""The one place that decides which libraries a user may see.

Deny-list semantics: a user sees every library unless an admin has hidden it
(a row in `user_library_access`). Admins see every library. A media file whose
`library_id` is still null (pre-backfill, or an install with no libraries
configured) is visible to everyone, so an in-progress backfill never hides
content.

Every content-serving path routes through this module:

- List endpoints add `visible_media_file_clause(...)` to the ready-file EXISTS so
  a hidden library's items never appear.
- Detail and per-file endpoints call `can_access_media_file` (or
  `can_access_item_files`) and answer 404 for something the user cannot see.
- `/api/stream/start` calls `can_access_media_file` and answers 403.
- The stream gateway (a separate process, user known only by id) calls
  `can_user_access_library(db, uid, library_id)` after the HMAC and session
  checks.
"""
from __future__ import annotations

import uuid
from typing import Iterable, Optional

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.models.library import Library, UserLibraryAccess
from app.models.media_file import MediaFile
from app.models.user import User


def _is_admin(user: User) -> bool:
    role = getattr(user, "role", None)
    # role can be the UserRole enum or a plain string depending on the caller.
    return getattr(role, "value", role) == "admin"


def hidden_library_ids(db: Session, user: User) -> set[uuid.UUID]:
    """Library ids hidden from this user. Empty for admins."""
    if _is_admin(user):
        return set()
    rows = db.scalars(
        select(UserLibraryAccess.library_id).where(UserLibraryAccess.user_id == user.id)
    ).all()
    return set(rows)


def all_library_ids(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(select(Library.id)).all())


def visible_library_ids(db: Session, user: User) -> set[uuid.UUID]:
    """Every library id this user may see (all minus hidden; all for admins)."""
    everything = all_library_ids(db)
    if _is_admin(user):
        return everything
    return everything - hidden_library_ids(db, user)


def can_access_library(db: Session, user: User, library_id: Optional[uuid.UUID]) -> bool:
    """A null library is visible to all. Otherwise: not in the user's hidden set."""
    if library_id is None:
        return True
    if _is_admin(user):
        return True
    return library_id not in hidden_library_ids(db, user)


def can_access_media_file(db: Session, user: User, mf: MediaFile) -> bool:
    return can_access_library(db, user, getattr(mf, "library_id", None))


def can_access_item_files(db: Session, user: User, files: Iterable[MediaFile]) -> bool:
    """True when at least one of the item's files is in a library the user can
    see (a null library id counts as visible). Admins always pass."""
    if _is_admin(user):
        return True
    hidden = hidden_library_ids(db, user)
    if not hidden:
        return True
    for f in files:
        lib = getattr(f, "library_id", None)
        if lib is None or lib not in hidden:
            return True
    return False


def can_user_access_library(
    db: Session, user_id, library_id: Optional[uuid.UUID],
) -> bool:
    """Gateway form: the user is known only by id (from the signed `uid`).

    A null library is visible to all. An admin sees all. Otherwise the library is
    visible unless a `user_library_access` row hides it."""
    if library_id is None:
        return True
    try:
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        return False
    user = db.get(User, uid)
    if user is None:
        return False
    if _is_admin(user):
        return True
    row = db.scalar(
        select(UserLibraryAccess.id).where(
            UserLibraryAccess.user_id == uid,
            UserLibraryAccess.library_id == library_id,
        )
    )
    return row is None


def visible_media_file_clause(hidden_ids: Iterable[uuid.UUID]):
    """A SQLAlchemy clause on `MediaFile` that is true for a visible file: its
    library is null (visible to all) or not in `hidden_ids`. Pass the result of
    `hidden_library_ids`; an empty set means everything is visible.

    Use inside the ready-file EXISTS subqueries of the list endpoints so a hidden
    library's items never surface."""
    ids = list(hidden_ids)
    if not ids:
        return true()
    return or_(MediaFile.library_id.is_(None), MediaFile.library_id.notin_(ids))
