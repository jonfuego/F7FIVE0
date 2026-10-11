"""Admin > Arr: Radarr, Sonarr and Lidarr settings, Test, pickers, webhook token.

Admin only, like Admin > Metadata for the TMDB key. Saved values live in
app_settings and win over `.env` (see services/arr_settings.py, the one place
that reads them). An API key is write-only: no response here ever carries a
stored key, only `has_key` and a masked tail. The webhook token is shown in
full because the admin has to paste it into each app.
"""
from __future__ import annotations

import logging
from typing import Annotated, Literal, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import scheduler
from app.api.deps import get_db, require_admin
from app.models.user import User
from app.services import android_app, arr_settings
from app.services.arr import LidarrClient, RadarrClient, SonarrClient
from app.services.arr._base import ArrAuthError, ArrClientError, ArrUnreachableError, _ArrClient
from app.config import settings

log = logging.getLogger("f7five0.admin.arr")
router = APIRouter()

ArrApp = Literal["radarr", "sonarr", "lidarr"]
_CLIENTS: dict[str, type[_ArrClient]] = {
    "radarr": RadarrClient, "sonarr": SonarrClient, "lidarr": LidarrClient,
}
_LABELS = {"radarr": "Radarr", "sonarr": "Sonarr", "lidarr": "Lidarr"}
WEBHOOK_MIN_LEN = 16


# -- schemas -------------------------------------------------------------
class ArrAppOut(BaseModel):
    app: ArrApp
    label: str
    configured: bool
    key_source: Optional[str]  # "admin", "env" or None
    has_key: bool
    masked: Optional[str]
    url: str
    url_source: str  # "admin" or "env"
    # Requests (Radarr and Sonarr only; None for Lidarr).
    supports_requests: bool
    quality_profile_id: Optional[int]
    quality_profile_source: Optional[str]
    root_folder: Optional[str]
    root_folder_source: Optional[str]


class ArrSettingsOut(BaseModel):
    apps: list[ArrAppOut]


class ArrSaveIn(BaseModel):
    """Every field is optional. url / root_folder: "" removes the saved value
    (`.env` applies again). api_key: blank leaves the saved key alone (it is a
    write-only box); DELETE .../key removes it. quality_profile_id: 0 removes."""
    url: Optional[str] = Field(default=None, max_length=300)
    api_key: Optional[str] = Field(default=None, max_length=200)
    quality_profile_id: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    root_folder: Optional[str] = Field(default=None, max_length=500)


class ArrTestIn(BaseModel):
    """Values to try. A blank field uses what is saved (or `.env`)."""
    url: Optional[str] = Field(default=None, max_length=300)
    api_key: Optional[str] = Field(default=None, max_length=200)


class ProfileOut(BaseModel):
    id: int
    name: str


class RootFolderOut(BaseModel):
    path: str
    free_space: Optional[int] = None


class ArrOptionsOut(BaseModel):
    profiles: list[ProfileOut]
    root_folders: list[RootFolderOut]
    error: Optional[str] = None


class ArrTestOut(BaseModel):
    ok: bool
    message: str
    version: Optional[str] = None
    options: Optional[ArrOptionsOut] = None


class WebhookOut(BaseModel):
    has_token: bool
    source: Optional[str]  # "admin", "env" or None
    token: Optional[str]
    paths: dict[str, str]
    base_urls: list[dict[str, str]]


class WebhookSaveIn(BaseModel):
    token: str = Field(min_length=WEBHOOK_MIN_LEN, max_length=200)


class WebhookGenerateIn(BaseModel):
    # A token already exists: generating a new one breaks every webhook that
    # still sends the old one, so the caller has to say it means that.
    rotate: bool = False


# -- helpers ------------------------------------------------------------
def _app_out(db: Session, app: str) -> ArrAppOut:
    src = arr_settings.key_source(db, app)
    key = arr_settings.api_key(app, db)
    requests_app = app in arr_settings.REQUEST_APPS
    return ArrAppOut(
        app=app, label=_LABELS[app],  # type: ignore[arg-type]
        configured=src is not None, key_source=src, has_key=bool(key),
        masked=arr_settings.masked(key) if key else None,
        url=arr_settings.url(app, db), url_source=arr_settings.url_source(db, app),
        supports_requests=requests_app,
        quality_profile_id=(arr_settings.quality_profile_id(app, db) or None) if requests_app else None,
        quality_profile_source=arr_settings.field_source(db, app, "quality_profile_id") if requests_app else None,
        root_folder=(arr_settings.root_folder(app, db) or None) if requests_app else None,
        root_folder_source=arr_settings.field_source(db, app, "root_folder") if requests_app else None,
    )


def _all_out(db: Session) -> ArrSettingsOut:
    return ArrSettingsOut(apps=[_app_out(db, a) for a in arr_settings.APPS])


def _clean_url(raw: str) -> str:
    """http(s) address with a host, no trailing slash; 422 otherwise."""
    value = raw.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=422, detail="Enter the full address, like http://127.0.0.1:7878")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPException(status_code=422, detail="The address should have no login, query or #fragment.")
    return value


def _friendly_error(app: str, exc: ArrClientError) -> str:
    label = _LABELS[app]
    if isinstance(exc, ArrAuthError):
        return f"{label} says the API key is wrong. Copy it from {label} > Settings > General."
    if isinstance(exc, ArrUnreachableError):
        return f"Can't reach {label} at that address. Check the URL and that {label} is running."
    if exc.status_code == 404:
        return f"That address answered, but it does not look like {label} (page not found). Check the URL."
    if exc.status_code and exc.status_code >= 400:
        return f"{label} answered with an error ({exc.status_code}). Check the URL."
    return f"That address answered, but it does not look like {label}. Check the URL."


def _options(client: _ArrClient, app: str) -> ArrOptionsOut:
    """Quality profiles and root folders; a failure becomes a short note."""
    try:
        profiles = client.quality_profiles() if app in arr_settings.REQUEST_APPS else []
        folders = client.root_folders() if app in arr_settings.REQUEST_APPS else []
    except ArrClientError as exc:
        return ArrOptionsOut(profiles=[], root_folders=[], error=_friendly_error(app, exc))
    return ArrOptionsOut(
        profiles=[
            ProfileOut(id=int(p["id"]), name=str(p.get("name") or p["id"]))
            for p in profiles if isinstance(p, dict) and isinstance(p.get("id"), int)
        ],
        root_folders=[
            RootFolderOut(path=str(f["path"]), free_space=f.get("freeSpace") if isinstance(f.get("freeSpace"), int) else None)
            for f in folders if isinstance(f, dict) and f.get("path")
        ],
    )


def _resolve(db: Session, app: str, body: Optional[ArrTestIn]) -> tuple[str, str]:
    """Typed values win; a blank one means the saved (or .env) value."""
    typed_url = (body.url or "").strip() if body else ""
    typed_key = (body.api_key or "").strip() if body else ""
    url = _clean_url(typed_url) if typed_url else arr_settings.url(app, db)
    return url, typed_key or arr_settings.api_key(app, db)


def _owns_changed(before: bool, after: bool, *, force: bool = False) -> None:
    """A key being set or removed moves a library between the *arr sync and the
    folder scan. Start both so the library follows right away."""
    if force or before != after:
        scheduler.trigger_full_sync_now()


# -- webhook token (declared before /{app} routes so "webhook" is never an app) ---
def _webhook_out(db: Session) -> WebhookOut:
    token = arr_settings.webhook_secret(db)
    bases: list[dict[str, str]] = []
    for label, value in (("Home network", android_app.home_url()), ("Public address", settings.public_url)):
        origin = android_app._clean_origin(value or "")
        if origin and origin not in [b["url"] for b in bases]:
            bases.append({"label": label, "url": origin})
    return WebhookOut(
        has_token=bool(token), source=arr_settings.webhook_source(db), token=token or None,
        paths={a: f"/api/webhooks/{a}" for a in arr_settings.APPS}, base_urls=bases,
    )


@router.get("/webhook", response_model=WebhookOut)
def get_webhook(
    response: Response,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> WebhookOut:
    response.headers["Cache-Control"] = "no-store"
    return _webhook_out(db)


@router.post("/webhook/generate", response_model=WebhookOut)
def generate_webhook(
    body: WebhookGenerateIn,
    response: Response,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> WebhookOut:
    """Make a random token. With one already set this needs rotate=true, and
    every *arr webhook must then be updated with the new token."""
    if arr_settings.webhook_secret(db) and not body.rotate:
        raise HTTPException(status_code=409, detail="A webhook token is already set. Rotating it breaks the webhooks until you paste the new one into each app.")
    arr_settings.save_webhook_secret(db, arr_settings.new_webhook_secret())
    db.commit()
    log.info("arr webhook token generated from the admin page")
    response.headers["Cache-Control"] = "no-store"
    return _webhook_out(db)


@router.put("/webhook", response_model=WebhookOut)
def put_webhook(
    body: WebhookSaveIn,
    response: Response,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> WebhookOut:
    """Save a token of the admin's choosing (replaces any earlier one)."""
    token = body.token.strip()
    if len(token) < WEBHOOK_MIN_LEN or any(c.isspace() for c in token):
        raise HTTPException(status_code=422, detail=f"Use at least {WEBHOOK_MIN_LEN} characters, no spaces.")
    arr_settings.save_webhook_secret(db, token)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _webhook_out(db)


@router.delete("/webhook", response_model=WebhookOut)
def delete_webhook(
    response: Response,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> WebhookOut:
    """Remove the saved token. ARR_WEBHOOK_SECRET in .env applies again; with
    none there, webhooks are refused (503) until one is generated."""
    arr_settings.clear_webhook_secret(db)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _webhook_out(db)


# -- per app ---------------------------------------------------------------
@router.get("", response_model=ArrSettingsOut)
def get_arr_settings(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArrSettingsOut:
    return _all_out(db)


@router.put("/{app}", response_model=ArrSettingsOut)
def put_arr_settings(
    app: ArrApp,
    body: ArrSaveIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArrSettingsOut:
    """Save what is given. Saving a key hands this library from the folder scan
    to the app; a sync starts at once. Nothing is checked against the app here:
    the Test button does that."""
    if app not in arr_settings.REQUEST_APPS and (body.quality_profile_id is not None or body.root_folder is not None):
        raise HTTPException(status_code=422, detail="Lidarr has no request settings.")
    before = arr_settings.configured(app)
    arr_settings.save(
        db, app,
        url=_clean_url(body.url) if (body.url or "").strip() else ("" if body.url is not None else None),
        api_key=body.api_key,
        quality_profile_id=body.quality_profile_id,
        root_folder=body.root_folder,
    )
    db.commit()
    # A new key (or a changed one) starts a sync; so does a key appearing.
    _owns_changed(before, arr_settings.configured(app), force=bool((body.api_key or "").strip()))
    log.info("%s settings saved from the admin page", app)
    return _all_out(db)


@router.delete("/{app}/key", response_model=ArrSettingsOut)
def delete_arr_key(
    app: ArrApp,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArrSettingsOut:
    """Remove the saved API key. The library goes back to the folder scan
    unless `.env` still has a key for this app."""
    before = arr_settings.configured(app)
    arr_settings.clear_key(db, app)
    db.commit()
    _owns_changed(before, arr_settings.configured(app))
    return _all_out(db)


@router.delete("/{app}", response_model=ArrSettingsOut)
def delete_arr_settings(
    app: ArrApp,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArrSettingsOut:
    """Remove everything saved for the app (key, URL, profile, root folder)."""
    before = arr_settings.configured(app)
    arr_settings.clear(db, app)
    db.commit()
    _owns_changed(before, arr_settings.configured(app))
    return _all_out(db)


@router.post("/{app}/test", response_model=ArrTestOut)
def test_arr(
    app: ArrApp,
    body: ArrTestIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArrTestOut:
    """Ask the app for its system status with the typed values (blank = saved
    or .env), without saving anything. On success also returns its quality
    profiles and root folders for the Requests pickers."""
    label = _LABELS[app]
    try:
        url, key = _resolve(db, app, body)
    except HTTPException as exc:
        return ArrTestOut(ok=False, message=str(exc.detail))
    if not key:
        return ArrTestOut(ok=False, message=f"Paste the {label} API key first.")
    with _CLIENTS[app](url, key, timeout=10.0) as client:
        try:
            status = client.system_status()
        except ArrClientError as exc:
            return ArrTestOut(ok=False, message=_friendly_error(app, exc))
        name = str(status.get("appName") or "")
        if name and name.lower() != app:
            return ArrTestOut(ok=False, message=f"That address is {name}, not {label}.")
        if not status.get("version"):
            return ArrTestOut(ok=False, message=f"That address answered, but it does not look like {label}. Check the URL.")
        version = str(status["version"])
        return ArrTestOut(ok=True, message=f"{label} {version} accepted the key.", version=version, options=_options(client, app))


@router.get("/{app}/options", response_model=ArrOptionsOut)
def arr_options(
    app: ArrApp,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArrOptionsOut:
    """Quality profiles and root folders from the app, using the saved values."""
    url, key = arr_settings.url(app, db), arr_settings.api_key(app, db)
    if not key:
        return ArrOptionsOut(profiles=[], root_folders=[], error=f"No {_LABELS[app]} API key is set.")
    with _CLIENTS[app](url, key, timeout=10.0) as client:
        return _options(client, app)
