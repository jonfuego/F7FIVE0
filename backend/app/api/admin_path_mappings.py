"""Admin > Library folders > Path mappings.

Admin only. A mapping says what a drive letter that Radarr, Sonarr or Lidarr
report (`N:`) means to the F7FIVE0 services, which cannot see a drive mapped in
someone's Windows login. See services/path_mappings.py.

    GET    /api/admin/path-mappings            the saved mappings, and the .env rules
    POST   /api/admin/path-mappings            add or change one, rewrite stored paths
    DELETE /api/admin/path-mappings?src=N:     take one away
    GET    /api/admin/path-mappings/arr-roots  each *arr root folder: can the service open it
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.services import arr_settings, path_map, path_mappings
from app.services.arr import LidarrClient, RadarrClient, SonarrClient

log = logging.getLogger("f7five0.admin.path_mappings")
router = APIRouter()

_CLIENTS = {"radarr": RadarrClient, "sonarr": SonarrClient, "lidarr": LidarrClient}


class MappingIn(BaseModel):
    src: str = Field(max_length=16)
    dst: str = Field(max_length=500)


class MappingOut(BaseModel):
    src: str
    dst: str


class MappingsOut(BaseModel):
    mappings: list[MappingOut]
    # Rules from PATH_REWRITE_RULES in .env: shown, not editable here.
    env_rules: list[MappingOut]
    # Set by POST: stored paths rewritten, and rows merged because the new path
    # already had one.
    rewritten: int = 0
    merged: int = 0


class RootOut(BaseModel):
    app: str
    label: str
    path: str
    translated: str
    mapped: bool
    reachable: bool
    drive: str | None


class RootErrorOut(BaseModel):
    app: str
    label: str
    error: str


class RootsOut(BaseModel):
    roots: list[RootOut]
    errors: list[RootErrorOut]


def _out(db: Session, *, rewritten: int = 0, merged: int = 0) -> MappingsOut:
    return MappingsOut(
        mappings=[MappingOut(**m) for m in path_mappings.read(db)],
        env_rules=[MappingOut(src=s, dst=d) for s, d in path_map.env_rules()],
        rewritten=rewritten, merged=merged,
    )


@router.get("", response_model=MappingsOut)
def list_mappings(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MappingsOut:
    return _out(db)


@router.post("", response_model=MappingsOut)
def save_mapping(
    body: MappingIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MappingsOut:
    """Add a mapping (or change the target of one for the same drive) and
    rewrite the paths already stored, in place, so watch history survives."""
    try:
        result = path_mappings.save(db, body.src, body.dst)
    except path_mappings.MappingError as exc:
        db.rollback()
        # The code is the detail, like the other admin endpoints; Admin words it.
        raise HTTPException(status_code=422, detail=exc.code)
    db.commit()
    return _out(db, **result)


@router.delete("", response_model=MappingsOut)
def delete_mapping(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    src: Annotated[str, Query(max_length=16)],
) -> MappingsOut:
    if not path_mappings.remove(db, src):
        raise HTTPException(status_code=404, detail="mapping_not_found")
    db.commit()
    return _out(db)


@router.get("/arr-roots", response_model=RootsOut)
def arr_roots(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RootsOut:
    """Each configured *arr app's root folders, as the app reports them, where the
    service would look (after the mappings) and whether it can open that. An app
    that cannot be reached is listed under `errors`."""

    def client_for(app: str):
        return _CLIENTS[app](*arr_settings.creds(app), timeout=10.0)

    report = path_mappings.arr_roots(db, client_for)
    return RootsOut(**report)
