"""The one outbound-fetch guard (SSRF) for anything a user or a feed can name.

A pasted art URL, a podcast feed, an episode enclosure, a chapters file: none of
them may be used to probe the LAN or the host itself. Every such fetch goes
through this module, which

- resolves the host ONCE per hop, refuses any address that is not globally
  routable (loopback, private, CGNAT and Tailscale 100.64/10, link-local,
  reserved, unspecified, multicast) and then connects to one of those exact
  addresses. The connection never does its own DNS lookup, so a rebinding name
  that answers public once and loopback next cannot steer the fetch. The URL,
  the Host header and the TLS server name and certificate check all stay on the
  original hostname,
- follows redirects by hand, at most `MAX_REDIRECTS` hops, and runs the same
  resolve, validate and pin on every hop, so a public URL cannot bounce the
  fetch onto an internal one,
- ignores proxy environment variables (`trust_env=False`), so a proxy set in
  the service environment cannot carry the request around the check,
- reads the body as a stream and stops at the caller's byte cap, so a fat file
  or a lying Content-Length cannot pull unbounded bytes into memory,
- sends the project User-Agent and uses connect and read timeouts.

`services/art.py` keeps its own error type and wraps `open_stream`; the podcast
code (feed, chapters, download, relay, OPML) uses `fetch_bytes` and
`open_stream` directly.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from app.config import PROJECT_URL

log = logging.getLogger("f7five0.net_guard")

# Redirect hops allowed on one fetch. Generous for CDN chains, bounded so a loop
# cannot spin, and each hop is checked.
MAX_REDIRECTS = 5

# Seconds. A host that accepts the connection and then says nothing must not
# hold a worker.
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 30

# Caps on what a fetch may read.
FEED_MAX_BYTES = 20 * 1024 * 1024
CHAPTERS_MAX_BYTES = 2 * 1024 * 1024
OPML_MAX_BYTES = 1 * 1024 * 1024

# Statuses that send the fetch somewhere else. Not 304: that one means "your copy
# is current", and the caller wants to see it.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Test seam: a transport that every guarded client uses instead of the network.
# None in production. The address check still runs in front of it.
_transport_override: Optional[httpx.BaseTransport] = None

# Test seam: the network backend a pinned transport dials through. None in
# production (real sockets).
_inner_backend_override: Optional[httpcore.NetworkBackend] = None


class NetGuardError(ValueError):
    """A guarded fetch was refused or failed. `status_code` is the HTTP status
    an endpoint should answer with; the message is safe to show an admin."""

    def __init__(self, message: str, status_code: int = 400, upstream_status: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.upstream_status = upstream_status


def user_agent() -> str:
    """`F7FIVE0/<version> (+https://github.com/jonfuego/F7FIVE0)`."""
    from app.services import server_version
    return f"F7FIVE0/{server_version.installed()} (+{PROJECT_URL})"


def client_transport() -> Optional[httpx.BaseTransport]:
    return _transport_override


def _is_blocked(ip: "ipaddress._BaseAddress") -> bool:
    """True for every address that is not publicly routable.

    `not is_global` covers loopback, RFC 1918, link-local, unique-local,
    reserved, unspecified and the shared address space 100.64.0.0/10 (CGNAT,
    where Tailscale lives). Multicast is refused explicitly. An IPv4 address
    wrapped in IPv6 (IPv4-mapped ::ffff:a.b.c.d, 6to4 2002::/16) is judged as
    the IPv4 address inside it.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _is_blocked(mapped)
    sixtofour = getattr(ip, "sixtofour", None)
    if sixtofour is not None:
        return _is_blocked(sixtofour)
    return bool(not ip.is_global or ip.is_multicast)


def resolve_public(host: str) -> list[str]:
    """Resolve `host` once and return its addresses, every one of them public.

    Raises NetGuardError when the host has no address, cannot be resolved, or
    maps to even one non-public address (a mixed answer is refused outright, so
    the caller never has to pick the safe one out of a list). The returned
    strings are what the connection must dial.
    """
    host = (host or "").strip()
    if not host:
        raise NetGuardError("url has no host", status_code=400)
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise NetGuardError(f"cannot resolve host {host}: {exc}", status_code=502)
    addresses: list[str] = []
    for info in infos:
        raw = info[4][0].split("%")[0]  # strip any IPv6 scope id
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            raise NetGuardError(f"unresolvable address for {host}", status_code=502)
        if _is_blocked(ip):
            raise NetGuardError(f"refusing to fetch from non-public address ({ip})", status_code=400)
        if raw not in addresses:
            addresses.append(raw)
    if not addresses:
        raise NetGuardError(f"cannot resolve host {host}", status_code=502)
    return addresses


def assert_public_host(url: str) -> None:
    """Reject a URL whose host resolves to a non-public address. For callers
    that only need the verdict; a fetch goes through `open_stream`, which also
    pins the connection to what was checked."""
    resolve_public(urlsplit(url).hostname or "")


def _check_scheme(url: str) -> None:
    if not url or not url.lower().startswith(("http://", "https://")):
        raise NetGuardError("url must be absolute http(s)", status_code=400)


class _PinnedBackend(httpcore.NetworkBackend):
    """Network backend that dials only the addresses it was given.

    httpcore asks it to connect to the URL's hostname; it ignores that name and
    tries the pre-validated addresses in order. TLS is started later by httpcore
    with the URL's hostname as the server name, so SNI and the certificate check
    still run against the real host. `inner` is a seam for tests.
    """

    def __init__(self, addresses: Iterable[str], inner: Optional[httpcore.NetworkBackend] = None) -> None:
        self.addresses = list(addresses)
        self._inner = inner if inner is not None else httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        last: Optional[Exception] = None
        for address in self.addresses:
            try:
                return self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        if last is not None:
            raise last
        raise httpcore.ConnectError(f"no address to connect to for {host}")

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("unix sockets are not allowed")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class _PinnedTransport(httpx.HTTPTransport):
    """An HTTPTransport whose connection pool dials `_PinnedBackend` only."""

    def __init__(self, addresses: Iterable[str], inner: Optional[httpcore.NetworkBackend] = None) -> None:
        super().__init__(http2=False, retries=0)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=True),
            max_connections=10,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedBackend(addresses, inner),
        )


def _make_client(
    addresses: list[str], headers: Optional[dict] = None,
    timeout: Optional[httpx.Timeout] = None,
) -> httpx.Client:
    merged = {"user-agent": user_agent()}
    merged.update({k.lower(): v for k, v in (headers or {}).items()})
    transport = client_transport()
    if transport is None:
        transport = _PinnedTransport(addresses, _inner_backend_override)
    return httpx.Client(
        timeout=timeout or httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=False,
        headers=merged,
        transport=transport,
        trust_env=False,
    )


class GuardedStream:
    """An open response, after every redirect hop passed the guard. The caller
    reads `response` and must `close()` (or use it as a context manager)."""

    def __init__(self, client: httpx.Client, response: httpx.Response, url: str) -> None:
        self._client = client
        self.response = response
        self.url = url
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.response.close()
        finally:
            self._client.close()

    def __enter__(self) -> "GuardedStream":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_stream(
    url: str, *, headers: Optional[dict] = None, method: str = "GET",
    timeout: Optional[httpx.Timeout] = None,
) -> GuardedStream:
    """Open `url`, following redirects by hand. On every hop the host is
    resolved once, every address is checked, and the connection is pinned to
    those addresses. Raises NetGuardError for a refused target, a redirect loop
    or a transport failure. The response status is NOT judged here (a 304, 206
    or 416 is the caller's business)."""
    _check_scheme(url)
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        addresses = resolve_public(urlsplit(current).hostname or "")
        client = _make_client(addresses, headers, timeout)
        try:
            request = client.build_request(method, current)
            response = client.send(request, stream=True)
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                response.close()
                client.close()
                if not location:
                    raise NetGuardError("redirect without a location header", status_code=502)
                current = urljoin(current, location)
                _check_scheme(current)
                continue
            return GuardedStream(client, response, current)
        except NetGuardError:
            client.close()
            raise
        except httpx.HTTPError as exc:
            client.close()
            raise NetGuardError(f"fetch failed ({type(exc).__name__})", status_code=502) from exc
        except Exception:
            client.close()
            raise
    raise NetGuardError("too many redirects", status_code=502)


@dataclass
class Fetched:
    status: int
    headers: httpx.Headers
    body: bytes
    url: str


def read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    """Read a streamed body, stopping the moment it crosses `max_bytes`."""
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise NetGuardError(f"response larger than the {max_bytes // 1024} KB limit", status_code=413)
    body = bytearray()
    try:
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise NetGuardError(f"response larger than the {max_bytes // 1024} KB limit", status_code=413)
    except httpx.HTTPError as exc:
        raise NetGuardError(f"fetch failed ({type(exc).__name__})", status_code=502) from exc
    return bytes(body)


def fetch_bytes(
    url: str, *, max_bytes: int, headers: Optional[dict] = None,
) -> Fetched:
    """GET `url` and return its body, at most `max_bytes`. A 304 comes back with
    an empty body; any other status of 400 or more raises (status 502, with the
    upstream status on the error)."""
    with open_stream(url, headers=headers) as stream:
        resp = stream.response
        if resp.status_code == 304:
            return Fetched(304, resp.headers, b"", stream.url)
        if resp.status_code >= 400 or 300 <= resp.status_code < 400:
            raise NetGuardError(
                f"upstream returned HTTP {resp.status_code}", status_code=502,
                upstream_status=resp.status_code,
            )
        body = read_limited(resp, max_bytes)
        return Fetched(resp.status_code, resp.headers, body, stream.url)
