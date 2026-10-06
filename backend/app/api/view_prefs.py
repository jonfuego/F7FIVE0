"""Saved library views for the current user.

The web reaches this through the library BFF (`/api/library/view-prefs` ->
`/api/view-prefs`); the app calls it directly with its Bearer token.

Endpoints:
  GET /view-prefs          all of the user's saved views as {key: value}
  PUT /view-prefs/{key}    set one view ({"value": <json>})

Keys: lowercase letters, digits and . _ : - (1 to 64 chars, starting with a
letter or digit), for example `music.browse` or `sort:movies`. Values are
any JSON up to MAX_VALUE_BYTES once serialized. A user has at most
MAX_KEYS_PER_USER keys.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models.user import User
from app.models.view_pref import UserViewPref


router = APIRouter(prefix="/view-prefs", tags=["library", "view-prefs"])

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
MAX_VALUE_BYTES = 2048
MAX_KEYS_PER_USER = 200


class ViewPrefsOut(BaseModel):
    prefs: dict[str, Any]


class ViewPrefIn(BaseModel):
    value: Any


class ViewPrefOut(BaseModel):
    key: str
    value: Any
    updated_at: datetime


@router.get("", response_model=ViewPrefsOut)
def list_view_prefs(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ViewPrefsOut:
    rows = db.scalars(select(UserViewPref).where(UserViewPref.user_id == user.id)).all()
    return ViewPrefsOut(prefs={r.view_key: r.value for r in rows})


@router.put("/{key}", response_model=ViewPrefOut)
def put_view_pref(
    key: Annotated[str, Path(max_length=64)],
    body: ViewPrefIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ViewPrefOut:
    if not KEY_RE.match(key):
        raise HTTPException(status_code=422, detail="bad_view_key")
    if body.value is None:
        raise HTTPException(status_code=422, detail="view_value_required")
    size = len(json.dumps(body.value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > MAX_VALUE_BYTES:
        raise HTTPException(status_code=413, detail="view_value_too_large")

    row = db.get(UserViewPref, (user.id, key))
    now = datetime.now(timezone.utc)
    if row is None:
        count = db.scalar(
            select(func.count()).select_from(UserViewPref).where(UserViewPref.user_id == user.id)
        ) or 0
        if count >= MAX_KEYS_PER_USER:
            raise HTTPException(status_code=409, detail="too_many_view_keys")
        row = UserViewPref(user_id=user.id, view_key=key, value=body.value, updated_at=now)
        db.add(row)
    else:
        row.value = body.value
        row.updated_at = now
    db.commit()
    return ViewPrefOut(key=key, value=row.value, updated_at=row.updated_at)
