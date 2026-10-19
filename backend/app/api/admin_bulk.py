"""Admin bulk-action endpoints.

Endpoints:
  GET  /api/admin/library/bulk-action  - current job status
  POST /api/admin/library/bulk-action  - queue a bulk action (409 if one is running)

All admin-only.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.services.bulk_actions import BULK_JOB_KEY, is_running
from app.models.app_setting import AppSetting

router = APIRouter(tags=["admin-bulk"])


class BulkActionRequest(BaseModel):
    action: str
    kind: str
    ids: list[uuid.UUID]
    params: Optional[dict] = None


@router.get("/bulk-action")
def get_bulk_status(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    row = db.get(AppSetting, BULK_JOB_KEY)
    return row.value if row else {"state": "idle"}


@router.post("/bulk-action", status_code=202)
def queue_bulk_action(
    body: BulkActionRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    if is_running(db):
        raise HTTPException(status_code=409, detail="bulk_job_running")
    from app import scheduler
    queued = scheduler.queue_bulk_action(
        body.action,
        body.kind,
        [str(i) for i in body.ids],
        body.params,
    )
    if not queued:
        raise HTTPException(status_code=503, detail="scheduler_not_running")
    return {"queued": True}
