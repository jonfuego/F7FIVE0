"""SEC-P1-1: only honour forwarded headers from a trusted direct peer.

The API and stream services sit behind a local front door (the Next proxy,
Cloudflare Tunnel, Caddy, Tailscale) that connects over loopback and sets
`CF-Connecting-IP` / `X-Forwarded-*`. A direct LAN client is not a proxy and
must not be able to spoof those headers to forge an audit IP, slip the login
throttle, or poison the host in a signed URL.

Two gates:

- `real_client_ip` reads `CF-Connecting-IP` / `X-Forwarded-For` only when the
  direct peer is a trusted proxy; otherwise the peer address wins.
- `forwarded_origin` builds an absolute origin from the forwarded/Host chain
  only when the peer is trusted and the host passes an allowlist (the
  configured public/home host, loopback, or a private LAN literal). Everything
  else falls back to `PUBLIC_URL`, so a hostile `X-Forwarded-Host` never ends
  up in a signed URL.

`trusted_proxies` (config) is a comma list of extra peer IPs/CIDRs to trust on
top of loopback, which is always trusted. The installer writes loopback.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request

from app.config import settings

# Loopback is always trusted: every supported front door (the Next proxy,
# cloudflared, Caddy, the Tailscale proxy) runs on the same host and reaches
# the backends over 127.0.0.1 / ::1.
_LOOPBACK_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)

# A host[:port] authority with no control characters, spaces, or commas. Used
# to reject header-injection attempts (CRLF, "evil.com, real.com") before the
# value is ever parsed or placed in a URL.
_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]+(?::\d{1,5})?$|^\[[0-9A-Fa-f:]+\](?::\d{1,5})?$")


def _trusted_networks() -> list[ipaddress._BaseNetwork]:
    nets: list[ipaddress._BaseNetwork] = list(_LOOPBACK_NETS)
    for raw in (settings.trusted_proxies or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            # A malformed entry is ignored rather than widening trust.
            continue
    return nets


def _parse_ip(value: Optional[str]) -> Optional[ipaddress._BaseAddress]:
    if not value:
        return None
    v = value.strip()
    try:
        return ipaddress.ip_address(v)
    except ValueError:
        # host:port (IPv4 or bracketed IPv6) -> strip the port and retry.
        if v.startswith("[") and "]" in v:
            v = v[1:v.index("]")]
        elif v.count(":") == 1:
            v = v.rsplit(":", 1)[0]
        try:
            return ipaddress.ip_address(v)
        except ValueError:
            return None


def peer_is_trusted(peer_ip: Optional[str]) -> bool:
    """True when the direct connection came from loopback or a configured proxy."""
    ip = _parse_ip(peer_ip)
    if ip is None:
        return False
    return any(ip in net for net in _trusted_networks())


def _first_hop(value: str) -> str:
    return value.split(",")[0].strip()


def real_client_ip(request: Request) -> str:
    """The client's IP, honouring forwarded headers only from a trusted peer.

    Used for the audit log and the login throttle (item 11 keys on this), so a
    direct LAN caller can neither forge another IP nor evade per-IP limits by
    rotating a spoofed `CF-Connecting-IP`.
    """
    peer = request.client.host if request.client else None
    if peer and peer_is_trusted(peer):
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return _first_hop(cf)
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return _first_hop(xff)
    return peer or "unknown"


def _hostname(authority: str) -> str:
    """The host part of an `authority` (host or host:port), lower-cased."""
    a = authority.strip().lower()
    if a.startswith("[") and "]" in a:
        return a[1:a.index("]")]
    if a.count(":") == 1:
        return a.rsplit(":", 1)[0]
    return a


def _allowed_hostnames() -> set[str]:
    names = {"localhost"}
    for configured in (settings.public_url, settings.home_url):
        host = urlsplit((configured or "").strip()).hostname
        if host:
            names.add(host.lower())
    return names


def host_is_allowed(authority: str) -> bool:
    """Whether `authority` (host[:port]) may appear in a signed URL.

    Allowed: the configured public/home host, loopback, or a private/link-local
    literal (home installs are reached at http://192.168.x.x:port and the
    operator cannot enumerate every LAN address). A public hostname that is not
    the configured one is rejected, which is what stops `X-Forwarded-Host`
    poisoning from pointing a signed URL at attacker infrastructure.
    """
    if not authority or not _HOST_RE.match(authority):
        return False
    host = _hostname(authority)
    if not host:
        return False
    if host in _allowed_hostnames():
        return True
    literal = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def forwarded_origin(request: Request) -> tuple[Optional[str], Optional[str]]:
    """`(host, proto)` from the forwarded/Host chain, or `(None, None)`.

    Returns a value only when the direct peer is trusted, the host passes the
    allowlist, and the scheme is http/https. Callers fall back to `PUBLIC_URL`.
    """
    peer = request.client.host if request.client else None
    if not peer_is_trusted(peer):
        return None, None
    host = _first_hop(
        request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    )
    if not host_is_allowed(host):
        return None, None
    proto = _first_hop(request.headers.get("x-forwarded-proto") or "") or request.url.scheme or "http"
    if proto not in ("http", "https"):
        return None, None
    return host, proto
