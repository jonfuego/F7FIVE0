"""Admin > Remote access: request validation, the file protocol with the
SYSTEM helper task, and run-state parsing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.api import remote_access as routes
from app.config import settings
from app.main import app
from app.services import remote_access as ra

TOKEN = "eyJhIjoiNmQ0YjE2MjgzYjBhNDY3ZDk0ZTkxZjNmNDdkMWQ0YjEiLCJ0IjoiYWJjIn0="
DUCK = "1a2b3c4d-1111-2222-3333-444455556666"


class FakeHelper:
    def __init__(self, available=True, fail=False):
        self._available = available
        self.fail = fail
        self.started = 0

    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        if self.fail:
            raise ra.HelperError("access denied")
        self.started += 1


@pytest.fixture()
def ra_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "remote_access_dir", str(tmp_path))
    monkeypatch.setattr(settings, "public_url", "")
    return tmp_path


@pytest.fixture()
def helper(client):
    h = FakeHelper()
    app.dependency_overrides[routes.get_helper] = lambda: h
    return h


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_status(ra_dir, **fields):
    now = datetime.now(timezone.utc)
    data = {"id": "a" * 32, "method": "cloudflare", "state": "running", "step": "x",
            "started_at": _iso(now), "updated_at": _iso(now)}
    data.update(fields)
    (ra_dir / "status.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validate_strips_scheme_and_case():
    assert ra.validate("Cloudflare", " HTTPS://Music.Example.com/ ")["host"] == "music.example.com"


@pytest.mark.parametrize("host", ["", "localhost", "music example.com", "music.example.com/x", "-a.example.com", "a..b.com", "music.example.com:443"])
def test_validate_rejects_bad_hosts(host):
    with pytest.raises(ra.RequestError):
        ra.validate("cloudflare", host)


def test_validate_tailscale_ignores_host_and_tokens():
    assert ra.validate("tailscale", "x.example.com", DUCK, TOKEN) == {
        "method": "tailscale", "host": "", "duckdns_token": "", "tunnel_token": "",
    }


def test_validate_duckdns_token_only_for_duckdns_names():
    assert ra.validate("portforward", "me.duckdns.org", DUCK)["duckdns_token"] == DUCK
    assert ra.validate("portforward", "music.example.com", DUCK)["duckdns_token"] == ""
    with pytest.raises(ra.RequestError) as e:
        ra.validate("portforward", "me.duckdns.org", "not-a-token; rm")
    assert e.value.code == "invalid_duckdns_token"


def test_validate_tunnel_token():
    assert ra.validate("token", "music.example.com", tunnel_token=TOKEN)["tunnel_token"] == TOKEN
    for bad in ("", "short", TOKEN + " --url http://evil", TOKEN + '"'):
        with pytest.raises(ra.RequestError) as e:
            ra.validate("token", "music.example.com", tunnel_token=bad)
        assert e.value.code == "invalid_tunnel_token"


def test_validate_unknown_method():
    with pytest.raises(ra.RequestError) as e:
        ra.validate("ngrok")
    assert e.value.code == "unknown_method"


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
CLOUDFLARED_LOG = """\
12:00:01 == Signing in to Cloudflare
12:00:02 Please open the following URL and log in with your Cloudflare account:
12:00:02 https://dash.cloudflare.com/argotunnel?aud=&callback=https%3A%2F%2Flogin.cloudflareaccess.org%2Fabc
12:00:02 Leave cloudflared running to download the cert automatically.
"""


def test_extract_sign_in_url_cloudflare():
    url = ra.extract_sign_in_url(CLOUDFLARED_LOG.splitlines())
    assert url == "https://dash.cloudflare.com/argotunnel?aud=&callback=https%3A%2F%2Flogin.cloudflareaccess.org%2Fabc"


def test_extract_sign_in_url_takes_latest_tailscale_link():
    lines = [
        "To authenticate, visit:",
        "        https://login.tailscale.com/a/1111aaaa",
        "Funnel is not enabled on your tailnet. To enable, visit:",
        "        https://login.tailscale.com/f/funnel?node=abc.",
    ]
    assert ra.extract_sign_in_url(lines) == "https://login.tailscale.com/f/funnel?node=abc"
    assert ra.extract_sign_in_url(["nothing here", "https://example.com/x"]) is None


def test_log_tail_redacts_tokens(ra_dir):
    (ra_dir / "run.log").write_text(
        "a\nnssm set F7FIVE0-Tunnel AppParameters tunnel run --token SECRETSECRET\n"
        "GET https://www.duckdns.org/update?domains=me&token=abc-123&ip=\n",
        encoding="utf-8",
    )
    tail = ra.read_log_tail(ra_dir / "run.log")
    assert "SECRETSECRET" not in "\n".join(tail) and "abc-123" not in "\n".join(tail)
    assert tail[1].endswith("--token ***")


# ---------------------------------------------------------------------------
# Starting a run
# ---------------------------------------------------------------------------
def test_start_writes_request_and_queued_status(client, ra_dir, helper):
    r = client.post("/api/admin/remote-access", json={"method": "cloudflare", "host": "music.example.com"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["state"] == "queued" and body["method"] == "cloudflare"
    assert helper.started == 1
    req = json.loads((ra_dir / "request.json").read_text())
    assert req["method"] == "cloudflare" and req["host"] == "music.example.com"
    assert req["id"] == body["id"] and len(req["id"]) == 32
    assert client.get("/api/admin/remote-access/run").json()["state"] == "queued"


def test_start_rejects_bad_input(client, ra_dir, helper):
    r = client.post("/api/admin/remote-access", json={"method": "cloudflare", "host": "bad host"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_host"
    r = client.post("/api/admin/remote-access", json={"method": "off"})
    assert r.status_code == 400
    assert helper.started == 0
    assert not (ra_dir / "request.json").exists()


def test_start_refused_while_a_run_is_active(client, ra_dir, helper):
    _write_status(ra_dir, state="signin")
    r = client.post("/api/admin/remote-access", json={"method": "tailscale"})
    assert r.status_code == 409 and r.json()["detail"] == "run_active"
    assert helper.started == 0


def test_stale_run_reports_failed_and_allows_a_new_one(client, ra_dir, helper):
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_status(ra_dir, state="queued", updated_at=_iso(old))
    run = client.get("/api/admin/remote-access/run").json()
    assert run["state"] == "failed" and "didn't start" in run["error"]
    assert client.post("/api/admin/remote-access", json={"method": "tailscale"}).status_code == 202


def test_helper_missing_is_503(client, ra_dir):
    app.dependency_overrides[routes.get_helper] = lambda: FakeHelper(available=False)
    r = client.post("/api/admin/remote-access", json={"method": "tailscale"})
    assert r.status_code == 503 and r.json()["detail"] == "helper_unavailable"


def test_helper_start_failure_marks_run_failed(client, ra_dir):
    app.dependency_overrides[routes.get_helper] = lambda: FakeHelper(fail=True)
    r = client.post("/api/admin/remote-access", json={"method": "tailscale"})
    assert r.status_code == 503 and r.json()["detail"] == "helper_failed"
    assert not (ra_dir / "request.json").exists()
    assert client.get("/api/admin/remote-access/run").json()["state"] == "failed"


def test_turn_off_queues_method_off(client, ra_dir, helper):
    r = client.delete("/api/admin/remote-access")
    assert r.status_code == 202 and r.json()["method"] == "off"
    assert json.loads((ra_dir / "request.json").read_text())["method"] == "off"


# ---------------------------------------------------------------------------
# Run state while signing in, cancel
# ---------------------------------------------------------------------------
def test_signin_state_shows_link_and_countdown(client, ra_dir):
    deadline = datetime.now(timezone.utc) + timedelta(seconds=300)
    _write_status(ra_dir, state="signin", sign_in_deadline=_iso(deadline))
    (ra_dir / "run.log").write_text(CLOUDFLARED_LOG, encoding="utf-8")
    run = client.get("/api/admin/remote-access/run").json()
    assert run["state"] == "signin"
    assert run["sign_in_url"].startswith("https://dash.cloudflare.com/argotunnel")
    assert 290 <= run["sign_in_seconds_left"] <= 300
    assert len(run["log"]) == 4


def test_cancel_active_run_sets_flag(client, ra_dir):
    _write_status(ra_dir, state="signin")
    assert client.post("/api/admin/remote-access/cancel").status_code == 202
    assert (ra_dir / "cancel").exists()


def test_cancel_stale_run_marks_it_cancelled(client, ra_dir):
    _write_status(ra_dir, state="running", updated_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=10)))
    assert client.post("/api/admin/remote-access/cancel").json()["state"] == "cancelled"
    assert not (ra_dir / "cancel").exists()


# ---------------------------------------------------------------------------
# Current setup
# ---------------------------------------------------------------------------
def test_status_reports_method_and_pending_address(client, ra_dir, helper, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://old.example.com")
    (ra_dir / "current.json").write_text(json.dumps({"method": "cloudflare", "public_url": "https://music.example.com"}))
    body = client.get("/api/admin/remote-access", params={"probe": "false"}).json()
    assert body["available"] is True
    assert body["method"] == "cloudflare"
    assert body["public_url"] == "https://old.example.com"
    assert body["pending_public_url"] == "https://music.example.com"
    assert body["reachable"] is None
    assert body["run"]["state"] == "idle"
    assert body["web_port"] == settings.web_port


def test_infer_method_for_older_installs():
    assert ra.infer_method("", None, None, None) is None
    assert ra.infer_method("https://f7five0.tail12.ts.net", None, None, None) == "tailscale"
    assert ra.infer_method("https://m.example.com", None, "running", None) == "cloudflare"
    assert ra.infer_method("https://m.example.com", None, None, "running") == "portforward"
    assert ra.infer_method("https://m.example.com", {"method": "token"}, "running", None) == "token"


def test_non_admin_is_refused(client, ra_dir, helper):
    from app.api.deps import require_admin

    def deny():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="admin_required")

    app.dependency_overrides[require_admin] = deny
    assert client.get("/api/admin/remote-access/run").status_code == 403
    assert client.post("/api/admin/remote-access", json={"method": "tailscale"}).status_code == 403
