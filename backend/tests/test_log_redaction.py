"""The TMDB key must never reach a log.

httpx logs every request URL at INFO, and a TMDB URL carries `api_key=<key>`
in its query string. Two layers: httpx and httpcore are held at WARNING, and a
filter on the root handler rewrites any `api_key=` value to `***` in every
record, so exception text that carries a URL is covered too.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.config import settings


@pytest.fixture()
def redacting(caplog):
    """The real filter, installed on the handlers of this test's root logger."""
    from app import log_redact

    caplog.set_level(logging.DEBUG)
    log_redact.install()
    yield caplog
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def test_redact_replaces_the_value_and_keeps_the_rest():
    from app import log_redact

    out = log_redact.redact("GET https://api.themoviedb.org/3/search/movie?api_key=SECRET&query=heat HTTP/1.1")
    assert "SECRET" not in out
    assert "api_key=***&query=heat" in out
    assert log_redact.redact("no key here") == "no key here"
    assert log_redact.redact("API_KEY=ABC123") == "API_KEY=***"
    assert log_redact.redact("url='https://x/y?a=1&api_key=SECRET'") == "url='https://x/y?a=1&api_key=***'"


def test_a_record_with_a_key_in_the_message_is_written_with_stars(redacting):
    logging.getLogger("f7five0.test").warning("fetch https://api.themoviedb.org/3/movie/1?api_key=SECRET failed")
    assert "SECRET" not in redacting.text
    assert "api_key=***" in redacting.text


def test_a_key_in_the_log_arguments_is_redacted(redacting):
    logging.getLogger("f7five0.test").warning("fetch %s failed (%d)", "https://x/y?api_key=SECRET", 404)
    assert "SECRET" not in redacting.text
    assert "api_key=*** failed (404)" in redacting.text
    logging.getLogger("f7five0.test").warning("by name %(u)s", {"u": "https://x/y?api_key=SECRET"})
    assert "SECRET" not in redacting.text


def test_a_key_inside_exception_text_is_redacted(redacting):
    log = logging.getLogger("f7five0.test")
    try:
        raise RuntimeError("Client error for url 'https://api.themoviedb.org/3/movie/1?api_key=SECRET'")
    except RuntimeError as exc:
        log.warning("tmdb failed: %s", exc)
        log.exception("tmdb blew up")
    assert "SECRET" not in redacting.text
    assert "api_key=***" in redacting.text


def test_httpx_stays_quiet_and_even_loud_httpx_is_redacted(redacting):
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpx").info('HTTP Request: GET https://api.themoviedb.org/3/x?api_key=SECRET "HTTP/1.1 200 OK"')
    assert "SECRET" not in redacting.text
    assert "api_key=***" in redacting.text


def test_a_tmdb_search_through_the_real_client_logs_no_key(redacting, monkeypatch):
    from app.services.metadata import tmdb

    monkeypatch.setattr(settings, "tmdb_api_key", "SECRETKEY123")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "SECRETKEY123"
        return httpx.Response(200, json={"results": [{"id": 603, "overview": "x"}]})

    monkeypatch.setattr(tmdb, "http_client", lambda *a, **k: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(tmdb, "cache_read", lambda *a, **k: None)
    monkeypatch.setattr(tmdb, "cache_write", lambda *a, **k: None)
    monkeypatch.setattr(tmdb, "_rate_wait", lambda: None)
    # What a server that logged httpx at INFO would have written.
    logging.getLogger("httpx").setLevel(logging.INFO)

    with tmdb.TMDBClient() as cli:
        hit = cli.search("movie", "The Matrix", 1999)

    assert hit and hit["id"] == 603
    assert "SECRETKEY123" not in redacting.text


@pytest.mark.parametrize("module", ["main", "stream", "cli"])
def test_each_entry_point_installs_the_filter_after_it_configures_logging(module):
    """The API, the stream gateway and the CLI all call log_redact.install()
    right after logging.basicConfig, so httpx is quiet and the filter is on the
    root handler in every process that talks to TMDB."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "app" / f"{module}.py").read_text(encoding="utf-8")
    configs = source.count("logging.basicConfig(")
    installs = source.count("log_redact.install()")
    assert configs >= 1
    assert installs >= configs, f"app/{module}.py configures logging {configs}x but installs the filter {installs}x"
    assert "from app import log_redact" in source or "import log_redact" in source
