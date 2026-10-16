"""Keep a DuckDNS name pointed at this PC.

Port forwarding with a DuckDNS name used to run a hidden PowerShell scheduled
task every 5 minutes. Defender flagged that as malware, and the token sat in
the task arguments. The API's scheduler now makes the call (job
`duckdns_refresh`), with the token read from the private .env.

The token travels in the request URL, so nothing here logs the URL, the token,
or an exception message from the HTTP library (which can quote the URL). The
answer is stored under app_settings `duckdns_status` as
`{checked_at, ok, error}`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import PROJECT_URL, settings
from app.services import app_settings, server_version

STATUS_KEY = "duckdns_status"
UPDATE_URL = "https://www.duckdns.org/update"
TIMEOUT_SEC = 15.0


def _user_agent() -> str:
    return f"F7FIVE0/{server_version.installed()} (+{PROJECT_URL})"


def _now(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def refresh(db, client: Optional[httpx.Client] = None, now: Optional[datetime] = None) -> dict:
    """Ask DuckDNS to point the configured name at this PC's public address
    (blank `ip=` means "the address you see"). Stores and returns
    `{checked_at, ok, error}`. A network failure is stored, never raised, and
    the error text never contains the token. The caller commits."""
    domain = settings.duckdns_domain.strip()
    token = settings.duckdns_token.strip()
    result = {"checked_at": _now(now), "ok": False, "error": None}
    if not domain or not token:
        result["error"] = "DuckDNS is not set up."
        app_settings.put(db, STATUS_KEY, result)
        return result

    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT_SEC, trust_env=False, follow_redirects=False)
    try:
        r = c.get(
            UPDATE_URL,
            params={"domains": domain, "token": token, "ip": ""},
            headers={"User-Agent": _user_agent()},
        )
        if r.status_code == 200 and r.text.strip() == "OK":
            result["ok"] = True
        elif r.status_code == 200:
            result["error"] = "DuckDNS refused the update. Check the name and token."
        else:
            result["error"] = f"DuckDNS answered HTTP {r.status_code}."
    except httpx.TimeoutException:
        result["error"] = "DuckDNS did not answer in time."
    except httpx.HTTPError:
        # The library's message can quote the request URL, which holds the token.
        result["error"] = "Could not reach DuckDNS."
    finally:
        if own:
            c.close()
    app_settings.put(db, STATUS_KEY, result)
    return result
