"""The one outbound-fetch guard (SSRF) for anything a user or a feed can name.

A pasted art URL, a podcast feed, an episode enclosure, a chapters file: none of
them may be used to probe the LAN or the host itself. Every such fetch goes
through this module, which

- resolves the host and refuses loopback, private, link-local, reserved,
  unspecified and multicast addresses (`assert_public_host`),
- follows redirects by hand, at most `MAX_REDIRECTS` hops, and runs the same
  check again on every hop, so a public URL cannot bounce the fetch onto an
  internal one,
- reads the body as a stream and stops at the caller's byte cap, so a fat file
  or a lying Content-Length cannot pull unbounded bytes into memory,
- sends the project User-Agent and uses connect and read timeouts.

`services/art.py` keeps its own error type and wraps `assert_public_host`;
the podcast code (feed, chapters, download, relay, OPML) uses `fetch_bytes` and
`open_stream` directly.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

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
# None in production.
_transport_override: Optional[httpx.BaseTransport] = None


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
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_unspecified or ip.is_multicast
    )


def assert_public_host(url: str) -> None:
    """Reject a URL whose host resolves to a non-public address.

    Resolves every address the host maps to and rejects loopback, private,
    link-local, reserved, unspecified and multicast ranges (an IPv4-mapped IPv6
    address is judged as the IPv4 address inside it). Called on the original URL
    and again on every redirect target.
    """
    host = (urlsplit(url).hostname or "").strip()
    if not host:
        raise NetGuardError("url has no host", status_code=400)
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise NetGuardError(f"cannot resolve host {host}: {exc}", status_code=502)
    for info in infos:
        raw = info[4][0].split("%")[0]  # strip any IPv6 scope id
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            raise NetGuardError(f"unresolvable address for {host}", status_code=502)
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if _is_blocked(ip):
            raise NetGuardError(f"refusing to fetch from non-public address ({ip})", status_code=400)


def _check_scheme(url: str) -> None:
    if not url or not url.lower().startswith(("http://", "https://")):
        raise NetGuardError("url must be absolute http(s)", status_code=400)


def _make_client(headers: Optional[dict] = None) -> httpx.Client:
    merged = {"user-agent": user_agent()}
    merged.update({k.lower(): v for k, v in (headers or {}).items()})
    return httpx.Client(
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=False,
        headers=merged,
        transport=client_transport(),
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


def open_stream(url: str, *, headers: Optional[dict] = None, method: str = "GET") -> GuardedStream:
    """Open `url`, following redirects by hand with the guard on every hop.
    Raises NetGuardError for a refused target, a redirect loop or a transport
    failure. The response status is NOT judged here (a 304, 206 or 416 is the
    caller's business)."""
    _check_scheme(url)
    client = _make_client(headers)
    current = url
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            assert_public_host(current)
            request = client.build_request(method, current)
            response = client.send(request, stream=True)
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise NetGuardError("redirect without a location header", status_code=502)
                current = urljoin(current, location)
                _check_scheme(current)
                continue
            return GuardedStream(client, response, current)
        raise NetGuardError("too many redirects", status_code=502)
    except NetGuardError:
        client.close()
        raise
    except httpx.HTTPError as exc:
        client.close()
        raise NetGuardError(f"fetch failed ({type(exc).__name__})", status_code=502) from exc
    except Exception:
        client.close()
        raise


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
