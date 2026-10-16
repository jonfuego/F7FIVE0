"""The DuckDNS refresh runs inside the API, not as a hidden PowerShell task.

The token rides in the request URL, so these tests check that it is sent, that
the answer is stored, and that it never reaches a log line, the stored status
or an error message.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app import log_redact, scheduler
from app.config import settings
from app.services import app_settings, duckdns

# Fake on purpose: obviously not a real DuckDNS token.
FAKE_TOKEN = "00000000-0000-0000-0000-000000000000"
FAKE_DOMAIN = "examplehome"


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "duckdns_domain", FAKE_DOMAIN)
    monkeypatch.setattr(settings, "duckdns_token", FAKE_TOKEN)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ok_body_is_success_and_the_request_is_the_duckdns_update_call(configured, db_session):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        seen["ua"] = request.headers.get("user-agent", "")
        return httpx.Response(200, text="OK")

    result = duckdns.refresh(db_session, client=_client(handler))

    assert result["ok"] is True and result["error"] is None and result["checked_at"]
    assert seen["url"].host == "www.duckdns.org" and seen["url"].path == "/update"
    assert seen["url"].params["domains"] == FAKE_DOMAIN
    assert seen["url"].params["token"] == FAKE_TOKEN
    assert seen["url"].params["ip"] == ""
    assert seen["ua"].startswith("F7FIVE0/")


def test_status_is_stored_under_duckdns_status(configured, db_session):
    duckdns.refresh(db_session, client=_client(lambda r: httpx.Response(200, text="OK\n")))
    stored = app_settings.get(db_session, "duckdns_status")
    assert stored["ok"] is True
    assert set(stored) == {"checked_at", "ok", "error"}


def test_ko_body_is_a_failure_without_the_token(configured, db_session):
    result = duckdns.refresh(db_session, client=_client(lambda r: httpx.Response(200, text="KO")))
    assert result["ok"] is False
    assert result["error"]
    assert FAKE_TOKEN not in str(result)
    assert app_settings.get(db_session, "duckdns_status")["ok"] is False


def test_http_error_status_is_a_failure(configured, db_session):
    result = duckdns.refresh(db_session, client=_client(lambda r: httpx.Response(503, text="down")))
    assert result["ok"] is False and "503" in result["error"]


def test_network_error_is_stored_not_raised_and_hides_the_token(configured, db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        # httpx errors often quote the URL, which holds the token.
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    result = duckdns.refresh(db_session, client=_client(handler))
    assert result["ok"] is False and result["error"]
    assert FAKE_TOKEN not in str(result)
    assert FAKE_TOKEN not in str(app_settings.get(db_session, "duckdns_status"))


def test_timeout_is_stored_not_raised(configured, db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result = duckdns.refresh(db_session, client=_client(handler))
    assert result["ok"] is False and "time" in result["error"]


def test_nothing_is_called_when_not_configured(monkeypatch, db_session):
    monkeypatch.setattr(settings, "duckdns_domain", "")
    monkeypatch.setattr(settings, "duckdns_token", "")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call DuckDNS")

    result = duckdns.refresh(db_session, client=_client(handler))
    assert result["ok"] is False


def test_no_token_or_url_in_log_output(configured, db_session, caplog):
    caplog.set_level(logging.DEBUG)
    log_redact.install()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    duckdns.refresh(db_session, client=_client(handler))
    duckdns.refresh(db_session, client=_client(lambda r: httpx.Response(200, text="OK")))
    assert FAKE_TOKEN not in caplog.text
    assert "duckdns.org/update" not in caplog.text


def test_module_never_passes_the_url_or_token_to_a_logger():
    import re
    from pathlib import Path

    source = Path(duckdns.__file__).read_text(encoding="utf-8")
    for call in re.findall(r"\blog(?:ger)?\.\w+\(.*", source):
        assert "token" not in call.lower() and "UPDATE_URL" not in call


def test_a_duckdns_url_in_a_log_record_is_written_with_stars(caplog):
    # See also test_log_redaction.py: the token in the update URL is masked.
    caplog.set_level(logging.DEBUG)
    log_redact.install()
    logging.getLogger("f7five0.test").warning(
        "GET https://www.duckdns.org/update?domains=%s&token=%s&ip=", FAKE_DOMAIN, FAKE_TOKEN
    )
    assert FAKE_TOKEN not in caplog.text
    assert "token=***" in caplog.text


# --- scheduler ---------------------------------------------------------------
def test_scheduler_adds_the_job_when_both_settings_are_set(configured):
    sched = scheduler.start()
    try:
        job = sched.get_job(scheduler.JOB_DUCKDNS)
        assert job is not None and "duckdns" in job.id
        assert job.trigger.interval.total_seconds() == 300
        assert job.max_instances == 1
        assert job.next_run_time is not None
    finally:
        scheduler.shutdown()


@pytest.mark.parametrize("domain,token", [("", ""), (FAKE_DOMAIN, ""), ("", FAKE_TOKEN), ("  ", "  ")])
def test_scheduler_skips_the_job_unless_both_are_set(monkeypatch, domain, token):
    monkeypatch.setattr(settings, "duckdns_domain", domain)
    monkeypatch.setattr(settings, "duckdns_token", token)
    sched = scheduler.start()
    try:
        assert sched.get_job(scheduler.JOB_DUCKDNS) is None
    finally:
        scheduler.shutdown()
