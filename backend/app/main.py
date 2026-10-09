"""F7FIVE0 API entry point.

Run locally:
    uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import log_redact
from app.config import settings
from app.db import db_session, engine
from app.services import nas_auth, scan_status, server_version
from app.services.trusted_proxy import real_client_ip
from app import scheduler
from app.api import admin as admin_routes
from app.api import art as art_routes
from app.api import auth as auth_routes
from app.api import auto_playlist as auto_playlist_routes
from app.api import client as client_routes
from app.api import library as library_routes
from app.api import live as live_routes
from app.api import media_files as media_files_routes
from app.api import passkeys as passkeys_routes
from app.api import queue as queue_routes
from app.api import view_prefs as view_prefs_routes
from app.api import remote_access as remote_access_routes
from app.api import tracks as tracks_routes
from app.api import requests as requests_routes
from app.api import sessions as sessions_routes
from app.api import stream as stream_routes
from app.api import webhooks as webhook_routes

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx logs request URLs at INFO, and a TMDB URL carries the api key.
log_redact.install()
log = logging.getLogger("f7five0.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("F7FIVE0 API starting (env=%s)", settings.environment)
    # Verify database connectivity. Fail fast if Postgres is unreachable.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("Database reachable")
    except Exception:
        log.exception("Database connection failed at startup")
        raise
    # A scan still marked running belongs to a process that no longer exists
    # (the server was stopped mid-scan): mark it interrupted, not running.
    try:
        with db_session() as db:
            if scan_status.reset_stale(db):
                log.warning("the last folder scan was interrupted; its status was reset")
    except Exception:
        log.warning("could not reset a stale folder scan status", exc_info=True)
    # Connect any saved NAS sign-ins under this process's logon session, so a
    # UNC library share is readable from the first request (LocalSystem has no
    # NAS login of its own). Cheap when already connected; a no-op off Windows.
    try:
        nas_auth.ensure_all()
    except Exception:
        log.warning("NAS ensure_all at API startup raised", exc_info=True)
    # Start the *arr sync scheduler. Jobs run every 5 minutes, starting on
    # the first fire interval (not immediately on boot) so startup stays fast.
    scheduler.start()
    yield
    log.info("F7FIVE0 API shutting down")
    scheduler.shutdown(wait=False)
    engine.dispose()


app = FastAPI(
    title="F7FIVE0 API",
    # What Setup recorded in <install>/version.json (0.0.0-dev without Setup).
    version=server_version.installed(),
    lifespan=lifespan,
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.environment != "production" else None,
)

# CORS: only needed during dev when running web on :3001 hitting api on :8001
# directly. In production everything flows through the tunnel on one origin.
if settings.environment == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://127.0.0.1:{settings.web_port}", f"http://localhost:{settings.web_port}"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def client_ip_middleware(request: Request, call_next):
    """Resolve the real client IP, trusting CF-Connecting-IP / X-Forwarded-For
    only from a trusted proxy peer (SEC-P1-1). The audit log and login throttle
    read request.state.client_ip, so a direct LAN caller cannot forge it."""
    request.state.client_ip = real_client_ip(request)
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "f7five0-api",
        # Read live, not from app.version: the updater's health check waits
        # for this to show the new version once Setup has written version.json.
        "version": server_version.installed(),
        "env": settings.environment,
    }


@app.get("/api/ready")
async def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("readiness probe failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "database_unreachable"},
        )
    # TODO Phase 1: probe *arr APIs, disk mounts
    return {"status": "ready"}


# Routers
app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
# Passkeys (WebAuthn). Mounted under /api/auth so login/options + login/verify
# sit beside /api/auth/login and flow through the tunnel's auth ingress. Routes:
# /api/auth/passkey/{register,login}/{options,verify} and /api/auth/passkeys.
app.include_router(passkeys_routes.router, prefix="/api/auth", tags=["auth", "passkeys"])
# Native 2.0 self-service device sessions and client-support endpoints. Both
# sit at /api/... (NOT /api/admin/...), so the documented tunnel ingress
# routes them to the API on :8001.
app.include_router(sessions_routes.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(client_routes.router, prefix="/api/client", tags=["client"])
app.include_router(library_routes.router, prefix="/api", tags=["library"])
app.include_router(queue_routes.router, prefix="/api", tags=["library", "queue"])
app.include_router(view_prefs_routes.router, prefix="/api", tags=["library", "view-prefs"])
app.include_router(requests_routes.router, prefix="/api/requests", tags=["requests"])
app.include_router(auto_playlist_routes.router, prefix="/api", tags=["library", "auto-playlist"])
# Phase 2 smart-audio + track-selection read endpoints.
app.include_router(tracks_routes.router, prefix="/api", tags=["library", "tracks"])
app.include_router(media_files_routes.router, prefix="/api", tags=["library", "media-files"])
app.include_router(stream_routes.router, prefix="/api", tags=["stream"])
# Live channel (SSE) + server-clock endpoint. Mounted at /api so a request
# with a Bearer token (app) or the web BFF's cookie->bearer swap reaches it,
# and so the documented tunnel ingress routes it to the API on :8001. The live
# hub is in-process: the API runs one uvicorn worker (see CLAUDE.md and
# docs/realtime.md); multi-worker would need PostgreSQL LISTEN/NOTIFY.
app.include_router(live_routes.router, prefix="/api", tags=["live"])
app.include_router(webhook_routes.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(remote_access_routes.router, prefix="/api/admin/remote-access", tags=["admin", "remote-access"])
app.include_router(admin_routes.router, prefix="/api/admin", tags=["admin"])
app.include_router(art_routes.admin_router, prefix="/api/admin/art", tags=["admin", "art"])
app.include_router(art_routes.read_router, prefix="/api/art", tags=["art"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error"},
    )
