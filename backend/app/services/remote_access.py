"""Admin > Remote access: the web app's side of the helper protocol.

Setting up Tailscale, Cloudflare, or port forwarding needs administrator
rights (services, firewall rules, installers), and the API may run as a
non-admin account. Setup registers a scheduled task (F7FIVE0-RemoteAccess,
runs as SYSTEM) that this account may start. The protocol is a folder,
<install>/data/remote-access/:

  request.json  written here: {id, method, host, duckdns_token, tunnel_token}.
                The helper deletes it as soon as it has read it.
  status.json   written by the helper (and here, as "queued"): state, step,
                sign-in link and deadline, result. Heartbeat every ~5 s.
  run.log       the helper's log for the current run.
  cancel        flag file; the helper stops at its next check.
  current.json  the method in use after a successful run.

See installer/remote-access.ps1 for the other side.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol
from urllib.parse import urlsplit

import httpx

from app.config import _DATA_ROOT, settings

log = logging.getLogger("f7five0.remote_access")

METHODS = ("tailscale", "cloudflare", "portforward", "token")
NEEDS_HOST = ("cloudflare", "portforward", "token")
ACTIVE_STATES = frozenset({"queued", "running", "signin", "restarting"})
# The helper saves status at least every 5 s while it works; a restart of
# the API and web services can take ~30 s. Past this, a run that still
# claims to be active is treated as dead (helper crashed or never started).
STALE_AFTER_SECONDS = 90

HOST_RE = re.compile(
    r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$"
)
DUCKDNS_TOKEN_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
TUNNEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-+/=]{40,4096}$")
SIGN_IN_URL_RE = re.compile(r"https://(?:login\.tailscale\.com|dash\.cloudflare\.com)/\S+")
_REDACT_RES = (
    re.compile(r"(--token\s+)\S+"),
    re.compile(r"(token=)[^&\s]+"),
)


class RequestError(ValueError):
    """A bad request from the admin page. `code` is the API error detail."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def status(self) -> Path:
        return self.root / "status.json"

    @property
    def request(self) -> Path:
        return self.root / "request.json"

    @property
    def cancel(self) -> Path:
        return self.root / "cancel"

    @property
    def current(self) -> Path:
        return self.root / "current.json"

    @property
    def log(self) -> Path:
        return self.root / "run.log"


def paths() -> Paths:
    root = settings.remote_access_dir.strip() or str(_DATA_ROOT / "remote-access")
    return Paths(Path(root))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def _retry(fn, attempts: int = 5):
    # The helper replaces status.json while we may be reading it; Windows
    # answers with a sharing violation for a moment.
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


def read_json(path: Path) -> Optional[dict]:
    try:
        text = _retry(lambda: path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, PermissionError, OSError):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _retry(lambda: os.replace(tmp, path))


def read_log_tail(path: Path, lines: int = 60) -> list[str]:
    try:
        text = _retry(lambda: path.read_text(encoding="utf-8", errors="replace"))
    except (FileNotFoundError, PermissionError, OSError):
        return []
    out = [redact(line) for line in text.splitlines() if line.strip()]
    return out[-lines:]


def redact(text: str) -> str:
    for rx in _REDACT_RES:
        text = rx.sub(r"\1***", text)
    return text


def extract_sign_in_url(lines: list[str]) -> Optional[str]:
    """Last Tailscale / Cloudflare sign-in link printed by the helper."""
    found = None
    for line in lines:
        for m in SIGN_IN_URL_RE.finditer(line):
            found = m.group(0).rstrip(".),'\"")
    return found


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(method: str, host: str = "", duckdns_token: str = "", tunnel_token: str = "") -> dict:
    """Clean and check a request. Raises RequestError(code)."""
    method = (method or "").strip().lower()
    if method not in METHODS and method != "off":
        raise RequestError("unknown_method")
    host = (host or "").strip().lower()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.rstrip("/")
    duckdns_token = (duckdns_token or "").strip().lower()
    tunnel_token = (tunnel_token or "").strip()
    if method in NEEDS_HOST:
        if not host:
            raise RequestError("host_required")
        if not HOST_RE.match(host):
            raise RequestError("invalid_host")
    else:
        host = ""
    if method == "portforward" and host.endswith(".duckdns.org") and duckdns_token:
        if not DUCKDNS_TOKEN_RE.match(duckdns_token):
            raise RequestError("invalid_duckdns_token")
    else:
        duckdns_token = ""
    if method == "token":
        if not TUNNEL_TOKEN_RE.match(tunnel_token):
            raise RequestError("invalid_tunnel_token")
    else:
        tunnel_token = ""
    return {"method": method, "host": host, "duckdns_token": duckdns_token, "tunnel_token": tunnel_token}


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------
def _parse_time(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_stale(status: dict, now: Optional[datetime] = None) -> bool:
    if status.get("state") not in ACTIVE_STATES:
        return False
    updated = _parse_time(status.get("updated_at"))
    if updated is None:
        return True
    return ((now or _now()) - updated).total_seconds() > STALE_AFTER_SECONDS


def is_active(status: Optional[dict], now: Optional[datetime] = None) -> bool:
    return bool(status) and status.get("state") in ACTIVE_STATES and not is_stale(status, now)


def run_state(now: Optional[datetime] = None) -> dict:
    """What the admin page shows while (and after) a run happens."""
    p = paths()
    status = read_json(p.status)
    lines = read_log_tail(p.log)
    if not status:
        return {"state": "idle", "log": lines}
    now = now or _now()
    state = status.get("state") or "idle"
    error = status.get("error")
    if is_stale(status, now):
        state = "failed"
        error = error or (
            "The remote access helper didn't start."
            if status.get("state") == "queued"
            else "The remote access helper stopped responding."
        )
    sign_in_url = None
    deadline = None
    seconds_left = None
    if state == "signin":
        sign_in_url = status.get("sign_in_url") or extract_sign_in_url(lines)
        deadline = status.get("sign_in_deadline")
        d = _parse_time(deadline)
        if d is not None:
            seconds_left = max(0, int((d - now).total_seconds()))
    return {
        "id": status.get("id"),
        "method": status.get("method"),
        "host": status.get("host") or None,
        "state": state,
        "step": status.get("step"),
        "sign_in_url": sign_in_url,
        "sign_in_deadline": deadline,
        "sign_in_seconds_left": seconds_left,
        "public_url": status.get("public_url"),
        "error": redact(error) if isinstance(error, str) else None,
        "started_at": status.get("started_at"),
        "finished_at": status.get("finished_at"),
        "log": lines,
    }


# ---------------------------------------------------------------------------
# The helper (scheduled task)
# ---------------------------------------------------------------------------
class Helper(Protocol):
    def available(self) -> bool: ...
    def start(self) -> None: ...


class HelperError(RuntimeError):
    pass


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ScheduledTaskHelper:
    """Starts the SYSTEM task Setup registered (schtasks /Run)."""

    def __init__(self, task_name: str):
        self.task_name = task_name

    def _schtasks(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["schtasks.exe", *args, "/TN", self.task_name],
            capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW,
        )

    def available(self) -> bool:
        if os.name != "nt":
            return False
        try:
            return self._schtasks("/Query").returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def start(self) -> None:
        if os.name != "nt":
            raise HelperError("not_windows")
        try:
            r = self._schtasks("/Run")
        except (OSError, subprocess.SubprocessError) as exc:
            raise HelperError(str(exc)) from exc
        if r.returncode != 0:
            raise HelperError((r.stderr or r.stdout or "").strip() or f"schtasks exit {r.returncode}")


def get_helper() -> Helper:
    return ScheduledTaskHelper(settings.remote_access_task)


def start_run(helper: Helper, req: dict, requested_by: str) -> dict:
    """Write the request, mark the run queued, start the helper."""
    p = paths()
    current = read_json(p.status)
    if is_active(current):
        raise RequestError("run_active")
    run_id = uuid.uuid4().hex
    now = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        p.cancel.unlink()
    except FileNotFoundError:
        pass
    write_json(p.request, {"id": run_id, **req, "requested_by": requested_by, "requested_at": now})
    write_json(p.status, {
        "id": run_id, "method": req["method"], "host": req.get("host") or None,
        "state": "queued", "step": "Starting the remote access helper",
        "sign_in_url": None, "sign_in_deadline": None, "public_url": None, "error": None,
        "started_at": now, "updated_at": now, "finished_at": None,
    })
    try:
        p.log.write_text("", encoding="utf-8")
    except OSError:
        pass
    try:
        helper.start()
    except HelperError as exc:
        log.warning("remote access helper did not start: %s", exc)
        try:
            p.request.unlink()
        except FileNotFoundError:
            pass
        write_json(p.status, {
            "id": run_id, "method": req["method"], "host": req.get("host") or None,
            "state": "failed", "step": None, "error": "The remote access helper could not be started.",
            "started_at": now, "updated_at": now, "finished_at": now,
        })
        raise
    return run_state()


def cancel_run() -> dict:
    p = paths()
    status = read_json(p.status)
    if not status or status.get("state") not in ACTIVE_STATES:
        return run_state()
    if is_stale(status):
        now = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
        status.update({"state": "cancelled", "step": "Cancelled", "updated_at": now, "finished_at": now})
        write_json(p.status, status)
        try:
            p.request.unlink()
        except FileNotFoundError:
            pass
    else:
        p.cancel.write_text("cancel", encoding="utf-8")
    return run_state()


# ---------------------------------------------------------------------------
# Current setup
# ---------------------------------------------------------------------------
def service_state(name: str) -> Optional[str]:
    """'running', 'stopped', other lower-case state, or None if absent / not Windows."""
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True,
                           timeout=10, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", r.stdout)
    return m.group(1).lower() if m else None


def infer_method(public_url: str, current: Optional[dict], tunnel: Optional[str], proxy: Optional[str]) -> Optional[str]:
    """The method in use. current.json wins; older installs set PUBLIC_URL
    without writing it, so fall back to what is installed."""
    if current and current.get("method") in METHODS:
        return current["method"]
    if not public_url:
        return None
    host = urlsplit(public_url).hostname or ""
    if host.endswith(".ts.net"):
        return "tailscale"
    if tunnel:
        return "cloudflare"
    if proxy:
        return "portforward"
    return None


def probe(public_url: str, timeout: float = 6.0) -> Optional[bool]:
    """Can this server reach itself at its public address? None when unset.
    Port forwarding may fail this check from inside the home network even
    when it works from outside (routers without hairpin NAT)."""
    if not public_url:
        return None
    url = public_url.rstrip("/") + "/login"
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=False)
    except httpx.HTTPError:
        return False
    return r.status_code < 500
