"""The shared SSRF guard (services/net_guard.py): every podcast fetch goes
through it, on every redirect hop, and the size caps hold."""
from __future__ import annotations

import httpx
import pytest

from app.services import net_guard
from tests.podcast_helpers import install_dns, install_transport

PRIVATE = ["127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.1.5", "0.0.0.0"]


@pytest.fixture(autouse=True)
def _dns(monkeypatch):
    install_dns(monkeypatch)


@pytest.mark.parametrize("ip", PRIVATE)
def test_guard_rejects_private_ipv4_literals(ip):
    with pytest.raises(net_guard.NetGuardError):
        net_guard.assert_public_host(f"http://{ip}/feed.xml")


def test_guard_rejects_ipv6_loopback_and_mapped():
    with pytest.raises(net_guard.NetGuardError):
        net_guard.assert_public_host("http://[::1]/feed.xml")
    with pytest.raises(net_guard.NetGuardError):
        net_guard.assert_public_host("http://[::ffff:127.0.0.1]/feed.xml")


@pytest.mark.parametrize("host", ["internal.example", "loopback.example", "metadata.example", "v6loop.example"])
def test_guard_rejects_names_that_resolve_private(host):
    with pytest.raises(net_guard.NetGuardError):
        net_guard.assert_public_host(f"https://{host}/x")


def test_guard_allows_a_public_host():
    net_guard.assert_public_host("https://feeds.example.org/x.xml")


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.9", "169.254.1.1"])
def test_feed_fetch_to_private_host_never_sends_a_request(monkeypatch, ip):
    calls = install_transport(monkeypatch, lambda r: httpx.Response(200, content=b"<rss/>"))
    with pytest.raises(net_guard.NetGuardError):
        net_guard.fetch_bytes(f"http://{ip}/feed.xml", max_bytes=1000)
    assert len(calls) == 0


def test_redirect_hop_to_private_host_is_rejected(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "feeds.example.org":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, content=b"secret")

    calls = install_transport(monkeypatch, handler)
    with pytest.raises(net_guard.NetGuardError):
        net_guard.fetch_bytes("https://feeds.example.org/feed.xml", max_bytes=1000)
    assert calls.urls() == ["https://feeds.example.org/feed.xml"]


@pytest.mark.parametrize("target", ["http://127.0.0.1/x", "http://10.0.0.5/x", "http://169.254.169.254/latest", "http://[::1]/x"])
def test_redirect_to_each_private_range_is_rejected(monkeypatch, target):
    install_transport(monkeypatch, lambda r: httpx.Response(301, headers={"location": target}))
    with pytest.raises(net_guard.NetGuardError):
        net_guard.fetch_bytes("https://feeds.example.org/f", max_bytes=1000)


def test_redirect_chain_is_capped_at_five_hops(monkeypatch):
    assert net_guard.MAX_REDIRECTS == 5
    n = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["i"] += 1
        return httpx.Response(302, headers={"location": f"https://feeds.example.org/hop{n['i']}"})

    calls = install_transport(monkeypatch, handler)
    with pytest.raises(net_guard.NetGuardError) as ei:
        net_guard.fetch_bytes("https://feeds.example.org/start", max_bytes=1000)
    assert "redirect" in str(ei.value).lower()
    assert len(calls) == net_guard.MAX_REDIRECTS + 1


def test_five_redirects_then_a_body_is_fine(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        step = int(path.removeprefix("/hop") or 0) if path.startswith("/hop") else 0
        if step < 5:
            return httpx.Response(302, headers={"location": f"https://feeds.example.org/hop{step + 1}"})
        return httpx.Response(200, content=b"done")

    install_transport(monkeypatch, handler)
    out = net_guard.fetch_bytes("https://feeds.example.org/start", max_bytes=1000)
    assert out.status == 200 and out.body == b"done"


def test_body_over_the_cap_is_refused_even_without_content_length(monkeypatch):
    def chunks():
        for _ in range(10):
            yield b"x" * 500

    install_transport(monkeypatch, lambda r: httpx.Response(200, content=chunks()))
    with pytest.raises(net_guard.NetGuardError) as ei:
        net_guard.fetch_bytes("https://feeds.example.org/big", max_bytes=2000)
    assert ei.value.status_code == 413


def test_declared_content_length_over_the_cap_is_refused(monkeypatch):
    install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-length": "999999"}, content=b"x"))
    with pytest.raises(net_guard.NetGuardError):
        net_guard.fetch_bytes("https://feeds.example.org/big", max_bytes=2000)


def test_caps_and_user_agent():
    assert net_guard.FEED_MAX_BYTES == 20 * 1024 * 1024
    assert net_guard.CHAPTERS_MAX_BYTES == 2 * 1024 * 1024
    assert net_guard.OPML_MAX_BYTES == 1 * 1024 * 1024
    assert net_guard.CONNECT_TIMEOUT == 30 and net_guard.READ_TIMEOUT == 30
    assert net_guard.user_agent().startswith("F7FIVE0/")
    assert net_guard.user_agent().endswith("(+https://github.com/jonfuego/F7FIVE0)")


def test_requests_carry_the_project_user_agent(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, content=b"ok")

    install_transport(monkeypatch, handler)
    net_guard.fetch_bytes("https://feeds.example.org/x", max_bytes=100)
    assert seen["ua"] == net_guard.user_agent()


def test_art_still_uses_the_guard(monkeypatch):
    """services/art.py keeps its behaviour but takes the check from net_guard."""
    from app.services import art

    install_transport(monkeypatch, lambda r: httpx.Response(200, content=b"x"))
    with pytest.raises(art.ArtValidationError) as ei:
        art.fetch_url_bytes("http://127.0.0.1/poster.jpg")
    assert ei.value.status_code == 400
    assert art.net_guard is net_guard
