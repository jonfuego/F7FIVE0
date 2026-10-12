"""SEC: the guard resolves once and dials the address it checked (no DNS
rebinding), on every redirect hop, with the Host header and TLS server name
kept on the original hostname, and with no proxy environment in the way.

No test here touches the network. A fake httpcore backend records what the
pinned transport tried to dial and answers with a canned HTTP/1.1 reply.
"""
from __future__ import annotations

import socket

import httpcore
import httpx
import pytest

from app.services import art, net_guard

PUBLIC_A = "93.184.216.34"
PUBLIC_B = "151.101.1.69"


class FakeStream(httpcore.NetworkStream):
    def __init__(self, backend: "FakeBackend", reply: bytes) -> None:
        self.backend = backend
        self._reply = reply
        self.written = b""

    def read(self, max_bytes, timeout=None):
        out, self._reply = self._reply[:max_bytes], self._reply[max_bytes:]
        return out

    def write(self, buffer, timeout=None):
        self.written += buffer
        self.backend.requests.append(buffer)

    def close(self):
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.backend.tls_names.append(server_hostname)
        return self

    def get_extra_info(self, info):
        return None


def _http(status: str, body: bytes = b"", headers: str = "") -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n{headers}"
        f"Connection: close\r\n\r\n"
    ).encode() + body


class FakeBackend(httpcore.NetworkBackend):
    """Records every dial. `replies` is consumed one connection at a time;
    `refuse` lists addresses that fail to connect."""

    def __init__(self, replies, refuse=()):
        self.replies = list(replies)
        self.refuse = set(refuse)
        self.dialed: list[tuple[str, int]] = []
        self.tls_names: list = []
        self.requests: list[bytes] = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.dialed.append((host, port))
        if host in self.refuse:
            raise httpcore.ConnectError("refused")
        return FakeStream(self, self.replies.pop(0))


def _dns(monkeypatch, table):
    """getaddrinfo from a table of host -> list of answers, one answer per call
    (the last one repeats). Returns the per-host call counter."""
    calls: dict[str, int] = {}

    def fake(host, port, *args, **kwargs):
        n = calls.get(host, 0)
        calls[host] = n + 1
        answers = table[host]
        ip = answers[min(n, len(answers) - 1)]
        ips = ip if isinstance(ip, list) else [ip]
        out = []
        for one in ips:
            family = socket.AF_INET6 if ":" in one else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, 6, "", (one, 0)))
        return out

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", fake)
    return calls


@pytest.fixture()
def backend(monkeypatch):
    def install(replies, refuse=()):
        fb = FakeBackend(replies, refuse)
        monkeypatch.setattr(net_guard, "_inner_backend_override", fb)
        return fb
    # The pinned path needs the real transport, not a mock transport.
    monkeypatch.setattr(net_guard, "_transport_override", None)
    return install


# ---------------------------------------------------------------------------
# What counts as public
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ip", [
    "100.64.0.1", "100.64.1.1", "100.100.100.100", "100.127.255.254",
    "10.0.0.1", "172.16.5.5", "192.168.0.10", "127.0.0.1", "169.254.169.254",
    "0.0.0.0", "224.0.0.1", "198.18.0.1", "192.0.0.1", "240.0.0.1",
    "::1", "::", "fe80::1", "fc00::1", "ff02::1",
    "::ffff:10.0.0.1", "::ffff:127.0.0.1", "::ffff:100.64.1.1",
    "2002:7f00:0001::1", "2002:0a00:0001::1",
])
def test_every_non_global_address_is_refused(monkeypatch, ip):
    _dns(monkeypatch, {"h.example": [ip]})
    with pytest.raises(net_guard.NetGuardError) as ei:
        net_guard.resolve_public("h.example")
    assert ei.value.status_code == 400


@pytest.mark.parametrize("ip", [PUBLIC_A, PUBLIC_B, "2606:4700:4700::1111", "::ffff:93.184.216.34"])
def test_public_addresses_pass(monkeypatch, ip):
    _dns(monkeypatch, {"h.example": [ip]})
    assert net_guard.resolve_public("h.example") == [ip]


def test_one_private_address_in_the_answer_refuses_the_host(monkeypatch):
    _dns(monkeypatch, {"h.example": [[PUBLIC_A, "10.0.0.5"]]})
    with pytest.raises(net_guard.NetGuardError):
        net_guard.resolve_public("h.example")


def test_tailscale_and_mapped_literal_urls_are_refused_without_a_dial(backend):
    # IP literals go through the real resolver, which hands them back as-is.
    fb = backend([_http("200 OK", b"x")])
    for url in ("http://100.64.1.1/x", "http://[::ffff:10.0.0.1]/x"):
        with pytest.raises(net_guard.NetGuardError):
            net_guard.fetch_bytes(url, max_bytes=100)
    assert fb.dialed == []


# ---------------------------------------------------------------------------
# DNS rebinding: resolve once, dial that address
# ---------------------------------------------------------------------------
def test_rebinding_resolver_never_connects_to_loopback(monkeypatch, backend):
    fb = backend([_http("200 OK", b"hello")])
    # First lookup is public (the check); any later lookup would be loopback.
    calls = _dns(monkeypatch, {"rebind.example": [PUBLIC_A, "127.0.0.1"]})
    out = net_guard.fetch_bytes("http://rebind.example/feed.xml", max_bytes=100)
    assert out.body == b"hello"
    assert calls["rebind.example"] == 1
    assert fb.dialed == [(PUBLIC_A, 80)]
    assert all(host != "127.0.0.1" for host, _ in fb.dialed)


def test_https_dials_the_checked_address_on_443(monkeypatch, backend):
    fb = backend([_http("200 OK", b"ok")])
    _dns(monkeypatch, {"secure.example": [PUBLIC_A, "127.0.0.1"]})
    net_guard.fetch_bytes("https://secure.example/x", max_bytes=100)
    assert fb.dialed == [(PUBLIC_A, 443)]


def test_host_header_and_tls_server_name_stay_on_the_hostname(monkeypatch, backend):
    fb = backend([_http("200 OK", b"ok")])
    _dns(monkeypatch, {"secure.example": [PUBLIC_A]})
    net_guard.fetch_bytes("https://secure.example/x?y=1", max_bytes=100)
    assert fb.tls_names == ["secure.example"]
    sent = b"".join(fb.requests).decode("latin-1")
    assert sent.startswith("GET /x?y=1 HTTP/1.1\r\n")
    assert "Host: secure.example\r\n" in sent
    assert PUBLIC_A not in sent


def test_redirect_hop_is_resolved_and_pinned_again(monkeypatch, backend):
    fb = backend([
        _http("302 Found", headers="Location: https://cdn.example/f.xml\r\n"),
        _http("200 OK", b"body"),
    ])
    calls = _dns(monkeypatch, {"first.example": [PUBLIC_A], "cdn.example": [PUBLIC_B, "127.0.0.1"]})
    out = net_guard.fetch_bytes("https://first.example/f", max_bytes=100)
    assert out.body == b"body" and out.url == "https://cdn.example/f.xml"
    assert fb.dialed == [(PUBLIC_A, 443), (PUBLIC_B, 443)]
    assert calls == {"first.example": 1, "cdn.example": 1}
    assert fb.tls_names == ["first.example", "cdn.example"]


def test_redirect_hop_to_a_private_host_is_refused_and_never_dialed(monkeypatch, backend):
    fb = backend([
        _http("302 Found", headers="Location: http://inside.example/secret\r\n"),
        _http("200 OK", b"secret"),
    ])
    _dns(monkeypatch, {"first.example": [PUBLIC_A], "inside.example": ["10.0.0.5"]})
    with pytest.raises(net_guard.NetGuardError):
        net_guard.fetch_bytes("http://first.example/f", max_bytes=100)
    assert fb.dialed == [(PUBLIC_A, 80)]


def test_redirect_to_a_rebinding_second_host_is_pinned_to_its_first_answer(monkeypatch, backend):
    fb = backend([
        _http("301 Moved", headers="Location: http://evil.example/x\r\n"),
        _http("200 OK", b"fine"),
    ])
    _dns(monkeypatch, {"first.example": [PUBLIC_A], "evil.example": [PUBLIC_B, "169.254.169.254"]})
    net_guard.fetch_bytes("http://first.example/f", max_bytes=100)
    assert fb.dialed == [(PUBLIC_A, 80), (PUBLIC_B, 80)]


def test_next_address_is_tried_when_the_first_does_not_connect(monkeypatch, backend):
    fb = backend([_http("200 OK", b"ok")], refuse={PUBLIC_A})
    _dns(monkeypatch, {"two.example": [[PUBLIC_A, PUBLIC_B]]})
    net_guard.fetch_bytes("http://two.example/", max_bytes=100)
    assert fb.dialed == [(PUBLIC_A, 80), (PUBLIC_B, 80)]


def test_connect_failure_to_every_address_is_a_guard_error(monkeypatch, backend):
    backend([], refuse={PUBLIC_A})
    _dns(monkeypatch, {"down.example": [PUBLIC_A]})
    with pytest.raises(net_guard.NetGuardError) as ei:
        net_guard.fetch_bytes("http://down.example/", max_bytes=100)
    assert ei.value.status_code == 502


def test_environment_proxy_is_ignored(monkeypatch, backend):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    fb = backend([_http("200 OK", b"ok")])
    _dns(monkeypatch, {"p.example": [PUBLIC_A]})
    net_guard.fetch_bytes("http://p.example/", max_bytes=100)
    assert fb.dialed == [(PUBLIC_A, 80)]


def test_guarded_clients_do_not_trust_the_environment():
    client = net_guard._make_client([PUBLIC_A])
    try:
        assert client.trust_env is False
    finally:
        client.close()


def test_mock_transport_seam_still_works_and_still_checks_the_address(monkeypatch):
    from tests.podcast_helpers import install_dns, install_transport

    install_dns(monkeypatch)
    calls = install_transport(monkeypatch, lambda r: httpx.Response(200, content=b"ok"))
    assert net_guard.fetch_bytes("https://feeds.example.org/x", max_bytes=10).body == b"ok"
    assert calls.urls() == ["https://feeds.example.org/x"]
    with pytest.raises(net_guard.NetGuardError):
        net_guard.fetch_bytes("http://100.64.1.1/x", max_bytes=10)
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Art URL fetch uses the same guarded open
# ---------------------------------------------------------------------------
def test_art_fetch_is_pinned_like_every_other_fetch(monkeypatch, backend):
    fb = backend([_http("200 OK", b"\x89PNG-bytes")])
    _dns(monkeypatch, {"img.example": [PUBLIC_A, "127.0.0.1"]})
    assert art.fetch_url_bytes("http://img.example/p.png") == b"\x89PNG-bytes"
    assert fb.dialed == [(PUBLIC_A, 80)]
    sent = b"".join(fb.requests).decode("latin-1").lower()
    assert "user-agent: f7five0-art/1.0" in sent


def test_art_fetch_refuses_a_private_redirect_hop(monkeypatch, backend):
    fb = backend([_http("302 Found", headers="Location: http://inside.example/p.png\r\n")])
    _dns(monkeypatch, {"img.example": [PUBLIC_A], "inside.example": ["192.168.1.9"]})
    with pytest.raises(art.ArtValidationError) as ei:
        art.fetch_url_bytes("http://img.example/p.png")
    assert ei.value.status_code == 400
    assert fb.dialed == [(PUBLIC_A, 80)]


def test_art_fetch_refuses_tailscale_and_mapped_addresses():
    for url in ("http://100.64.1.1/p.png", "http://[::ffff:10.0.0.1]/p.png"):
        with pytest.raises(art.ArtValidationError) as ei:
            art.fetch_url_bytes(url)
        assert ei.value.status_code == 400


def test_art_fetch_keeps_its_size_cap_and_status_mapping(monkeypatch, backend):
    big = b"x" * 200
    monkeypatch.setattr(art, "_MAX_BYTES", 100)
    backend([_http("200 OK", big)])
    _dns(monkeypatch, {"img.example": [PUBLIC_A]})
    with pytest.raises(art.ArtValidationError) as ei:
        art.fetch_url_bytes("http://img.example/big.png")
    assert ei.value.status_code == 413

    backend([_http("404 Not Found", b"no")])
    with pytest.raises(art.ArtValidationError) as ei:
        art.fetch_url_bytes("http://img.example/missing.png")
    assert ei.value.status_code == 502


def test_art_has_no_redirect_loop_of_its_own():
    import inspect
    src = inspect.getsource(art.fetch_url_bytes)
    assert "client.stream" not in src
    assert "_assert_public_host" not in src
    assert not hasattr(art, "_assert_public_host")
