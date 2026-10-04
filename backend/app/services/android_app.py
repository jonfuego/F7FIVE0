"""The Android app this server hands out.

Setup copies the official phone APK that matches the server version into the
downloads folder (F7FIVE0_DOWNLOADS_DIR, default <install>/data/downloads):

  F7FIVE0-<version>.apk          64-bit (arm64-v8a), always shipped
  F7FIVE0-<version>-armv7.apk    32-bit (armeabi-v7a), only in some releases

Every download is stamped with this server's addresses (see apk_stamp.py), so
the app fills in the server on first launch. The stamp lists, in order: the
public address (PUBLIC_URL), the address the person downloaded from, and the
home network address. The app uses the first one that answers.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from app.config import _DATA_ROOT, settings
from app.services import apk_stamp

ABIS = ("arm64", "armv7")
_NAME = re.compile(r"^F7FIVE0-(?P<version>\d+\.\d+\.\d+)(?P<suffix>-armv7)?\.apk$", re.IGNORECASE)


@dataclass(frozen=True)
class Apk:
    path: Path
    version: str
    abi: str

    @property
    def name(self) -> str:
        return self.path.name


def downloads_dir() -> Path:
    raw = settings.f7five0_downloads_dir.strip()
    return Path(raw) if raw else _DATA_ROOT / "downloads"


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def find_apks(folder: Optional[Path] = None) -> dict[str, Apk]:
    """Newest phone APK per ABI. TV builds and other files are ignored."""
    folder = folder or downloads_dir()
    best: dict[str, Apk] = {}
    try:
        entries = list(folder.iterdir())
    except OSError:
        return best
    for entry in entries:
        m = _NAME.match(entry.name)
        if not m or not entry.is_file():
            continue
        abi = "armv7" if m.group("suffix") else "arm64"
        cur = best.get(abi)
        if cur is None or _version_key(m.group("version")) > _version_key(cur.version):
            best[abi] = Apk(path=entry, version=m.group("version"), abi=abi)
    return best


def _clean_origin(url: str) -> Optional[str]:
    """scheme://host[:port] of an http(s) URL, or None. Loopback addresses
    are dropped: a phone can never reach them."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return None
    try:
        if ipaddress.ip_address(host).is_loopback:
            return None
    except ValueError:
        pass
    return f"{parts.scheme}://{parts.netloc.lower()}"


def lan_ipv4() -> Optional[str]:
    """This machine's private IPv4 on the default route, or None. A UDP
    connect sends no packets; it only asks the OS which interface it would
    use."""
    for probe in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 1))
            ip = s.getsockname()[0]
        except OSError:
            continue
        finally:
            s.close()
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private and not addr.is_loopback and not addr.is_link_local:
            return ip
    return None


def home_url() -> Optional[str]:
    """Address on the home network: HOME_URL when set, else the LAN IP and
    the web port."""
    if settings.home_url.strip():
        return _clean_origin(settings.home_url)
    ip = lan_ipv4()
    return f"http://{ip}:{settings.web_port}" if ip else None


def server_addresses(request_origin: Optional[str]) -> list[str]:
    """What gets stamped: public address, the address used for this
    download, home address. Duplicates and unusable entries dropped."""
    out: list[str] = []
    for candidate in (settings.public_url, request_origin or "", home_url() or ""):
        origin = _clean_origin(candidate)
        if origin and origin not in out:
            out.append(origin)
    return out


def plan(apk: Apk, request_origin: Optional[str]) -> apk_stamp.StampPlan:
    return apk_stamp.plan_stamp(apk.path, {"v": 1, "servers": server_addresses(request_origin)})
