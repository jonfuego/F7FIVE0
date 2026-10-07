"""Server self-update: the GitHub check, the verified download, the rules for a
Setup you upload, and the web app's side of the protocol with the SYSTEM
updater task.

Installing an update needs administrator rights (services, Program Files-style
folders, PostgreSQL), and the API may run as a non-admin account. So Setup
registers a scheduled task (F7FIVE0-Update, runs as SYSTEM) that this account
may start. The protocol is a folder, <install>/data/updates/:

  request.json  written here: {id, setup_path, sha256, version, source}.
                The updater deletes it as soon as it has read it.
  status.json   phase, versions, error, log path. Written here as "queued" (and
                "downloading" before that); the updater takes over from there.
  incoming/     the verified Setup waiting to run (the updater refuses any
                path outside this folder).
  setup/        copies of past Setups, written by Setup itself, for rollback.
  backup/       pg_dump files, one per update.
  run/          the updater's own copy of itself (SYSTEM and Administrators only).

See installer/update.ps1 for the other side.

Trust. A Setup runs as SYSTEM, so nothing reaches it unless it is one of:
  - downloaded from a GitHub release over https from an allowlisted host and
    matching that release's SHA256SUMS.txt (source "github"), or
  - an upload whose SHA-256 matches the published release of its own version
    (source "release"), or
  - an upload with a valid Authenticode signature from UPDATE_SIGNER_SUBJECT
    (source "signed"; off while that setting is empty).
The same or an older version is never installed.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import struct
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Iterator, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import PROJECT_URL, _DATA_ROOT, _REPO_ROOT, settings
from app.services import app_settings, remote_access as ra, server_version
from app.services.security import verify_password

log = logging.getLogger("f7five0.updates")

SETTING_KEY = "update_check"
RELEASES_LATEST_URL = "https://api.github.com/repos/jonfuego/F7FIVE0/releases/latest"
RELEASE_BY_TAG_URL = "https://api.github.com/repos/jonfuego/F7FIVE0/releases/tags/{tag}"
SETUP_PREFIX = "F7FIVE0-Setup-"
SUMS_NAME = "SHA256SUMS.txt"

# Where a Setup or its checksums may be downloaded from. GitHub serves a
# release asset from github.com, then redirects to objects.githubusercontent.com
# (older releases) or release-assets.githubusercontent.com (current ones).
# Exact host names only: no suffix match, so "github.com.evil.example" fails.
DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
MAX_REDIRECTS = 5
MAX_SUMS_BYTES = 64 * 1024
MAX_NOTES_CHARS = 20000

ACTIVE_PHASES = frozenset({"queued", "downloading", "verifying", "backup", "installing", "health_check", "rolling_back"})
TERMINAL_PHASES = frozenset({"done", "rolled_back", "failed"})
# The updater touches status.json at least every ~5 s while it works, even
# during a long Setup. Past this, a run that still claims to be active is dead.
STALE_AFTER_SECONDS = 120

MAX_PASSWORD_FAILURES = 5
PASSWORD_WINDOW_SECONDS = 15 * 60

_TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")

MESSAGES = {
    "host_not_allowed": "That download address isn't one F7FIVE0 trusts, so nothing was downloaded.",
    "download_failed": "The download didn't finish. Try again in a few minutes.",
    "too_large": "That file is bigger than a F7FIVE0 Setup can be, so it was refused.",
    "hash_mismatch": "The download doesn't match its published checksum, so it was thrown away.",
    "no_checksum_line": "The release's checksum list has no entry for this Setup, so it was not installed.",
    "no_checksums": "This release has no checksums, so F7FIVE0 won't install it.",
    "no_setup": "This release has no Setup file to install.",
    "no_update": "There's no newer version to install. Check for updates first.",
    "not_newer": "That version isn't newer than the one installed. F7FIVE0 never installs the same or an older version.",
    "not_an_exe": "That file isn't a Windows program, so it was refused.",
    "no_version": "That file doesn't say which F7FIVE0 version it is, so it was refused.",
    "untrusted_setup": (
        "F7FIVE0 only installs a Setup that matches a published release or carries the F7FIVE0 signature. "
        "This file is neither, so it was refused."
    ),
    "release_unreachable": "Couldn't reach GitHub to check this file against the published release. Check the internet connection and try again.",
    "admin_password_required": "Enter your admin password to upload a Setup.",
    "admin_password_incorrect": "That isn't your admin password.",
    "too_many_attempts": "Too many wrong passwords. Wait 15 minutes and try again.",
    "update_running": "An update is already running. Wait for it to finish.",
    "helper_unavailable": "The updater isn't installed on this server. Run the new Setup by hand once; it adds the updater.",
    "helper_failed": "The server couldn't start the updater. See the F7FIVE0 logs, or run Setup again.",
    "github_unreachable": "Couldn't reach GitHub.",
    "rate_limited": "GitHub's rate limit stopped this check. It will try again later.",
    "no_release": "GitHub has no published release to offer yet.",
    "github_error": "GitHub answered with an error.",
}


class UpdateError(Exception):
    """A refused or failed update step. `code` is the API error detail; the
    admin page turns it into text."""

    def __init__(self, code: str, message: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.message = message or MESSAGES.get(code, code)


# ---------------------------------------------------------------------------
# Versions (semantic versioning)
# ---------------------------------------------------------------------------
def parse_version(text) -> Optional[tuple]:
    """(major, minor, patch, prerelease identifiers) or None. A leading "v" is
    allowed; +build metadata is ignored."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if t[:1] in ("v", "V"):
        t = t[1:]
    m = server_version.VERSION_RE.match(t)
    if not m:
        return None
    pre = tuple(m.group("pre").split(".")) if m.group("pre") else ()
    return int(m.group("major")), int(m.group("minor")), int(m.group("patch")), pre


def _pre_key(pre: tuple) -> tuple:
    # Numeric identifiers sort below alphanumeric ones; numbers compare as
    # numbers (beta.2 < beta.11).
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre)


def compare_versions(a: str, b: str) -> int:
    """-1, 0, or 1. 0.1.0-batch4 sorts below 0.1.0. Raises ValueError on junk."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        raise ValueError(f"not a version: {a!r} / {b!r}")
    if pa[:3] != pb[:3]:
        return -1 if pa[:3] < pb[:3] else 1
    if pa[3] == pb[3]:
        return 0
    if not pa[3]:
        return 1
    if not pb[3]:
        return -1
    ka, kb = _pre_key(pa[3]), _pre_key(pb[3])
    return -1 if ka < kb else (1 if ka > kb else 0)


def is_newer(latest: Optional[str], installed: str) -> bool:
    """True only when `latest` is strictly greater. Junk or None is never newer."""
    try:
        return latest is not None and compare_versions(latest, installed) > 0
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Releases and checksums
# ---------------------------------------------------------------------------
def parse_release(payload) -> Optional[dict]:
    """The parts of a GitHub release this server cares about, or None for a
    draft, a prerelease, or a tag that isn't vX.Y.Z. A release with no Setup or
    no SHA256SUMS.txt still parses (the page shows it, but it can't install)."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not _TAG_RE.match(tag):
        return None
    version = tag[1:]
    setup_name = f"{SETUP_PREFIX}{version}.exe"
    setup_url = sums_url = None
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        if name == setup_name:
            setup_url = url
        elif name == SUMS_NAME:
            sums_url = url
    notes = payload.get("body")
    notes = notes[:MAX_NOTES_CHARS] if isinstance(notes, str) else ""
    return {"version": version, "tag": tag, "notes": notes, "setup_url": setup_url, "sums_url": sums_url}


def find_sum(sums_text: str, filename: str) -> Optional[str]:
    """The lowercase SHA-256 listed for `filename` in a SHA256SUMS.txt
    ("<hash>  <name>" per line; a "*" before the name marks binary mode)."""
    for line in (sums_text or "").splitlines():
        m = re.match(r"^([0-9A-Fa-f]{64})\s+\*?(.+?)\s*$", line)
        if m and m.group(2) == filename:
            return m.group(1).lower()
    return None


# ---------------------------------------------------------------------------
# Talking to GitHub
# ---------------------------------------------------------------------------
def user_agent() -> str:
    return f"F7FIVE0/{server_version.installed()} (+{PROJECT_URL})"


def _client() -> httpx.Client:
    # No token, ever: the repository is public. Redirects are followed by hand
    # so every hop can be checked against the host allowlist.
    return httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False)


def _iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def stored_check(db) -> dict:
    row = app_settings.get(db, SETTING_KEY) or {}
    return {k: row.get(k) for k in ("checked_at", "latest", "notes", "setup_url", "sums_url", "error")}


def check_for_update(db, client: Optional[httpx.Client] = None, now: Optional[datetime] = None) -> dict:
    """Ask GitHub for the latest published release and store the answer under
    app_settings "update_check". Network trouble is stored as `error`, never
    raised, and the last good answer stays. The caller commits."""
    previous = stored_check(db)
    own = client is None
    c = client or _client()
    result = dict(previous)
    result["checked_at"] = _iso(now)
    try:
        r = c.get(RELEASES_LATEST_URL, headers={"User-Agent": user_agent(), "Accept": "application/vnd.github+json"})
        if r.status_code == 200:
            rel = parse_release(r.json())
            if rel is None:
                result["error"] = MESSAGES["no_release"]
                result.update(latest=None, notes=None, setup_url=None, sums_url=None)
            else:
                result.update(latest=rel["version"], notes=rel["notes"], setup_url=rel["setup_url"],
                              sums_url=rel["sums_url"], error=None)
        elif r.status_code in (403, 429):
            result["error"] = MESSAGES["rate_limited"]
        elif r.status_code == 404:
            result["error"] = MESSAGES["no_release"]
            result.update(latest=None, notes=None, setup_url=None, sums_url=None)
        else:
            result["error"] = f"{MESSAGES['github_error']} (HTTP {r.status_code})"
    except (httpx.HTTPError, ValueError) as exc:
        log.info("update check failed: %s", exc)
        result["error"] = MESSAGES["github_unreachable"]
    finally:
        if own:
            c.close()
    app_settings.put(db, SETTING_KEY, result)
    return result


def check_host(url: str) -> None:
    """Raise unless `url` is https on an allowlisted download host (default
    port, no embedded credentials)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "https" or host not in DOWNLOAD_HOSTS or port not in (None, 443) or parts.username or parts.password:
        raise UpdateError("host_not_allowed")


def _iter_download(url: str, max_bytes: int, client: httpx.Client) -> Iterator[tuple[bytes, int]]:
    """Yield (chunk, declared total or 0) from an allowlisted https URL,
    following redirects only to allowlisted hosts and stopping past max_bytes."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        check_host(current)
        try:
            with client.stream("GET", current, headers={"User-Agent": user_agent()}) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    location = r.headers.get("location")
                    if not location:
                        raise UpdateError("download_failed")
                    current = urljoin(current, location)
                    continue
                if r.status_code != 200:
                    raise UpdateError("download_failed")
                declared = r.headers.get("content-length", "")
                total = int(declared) if declared.isdigit() else 0
                if total > max_bytes:
                    raise UpdateError("too_large")
                done = 0
                for chunk in r.iter_bytes(65536):
                    done += len(chunk)
                    if done > max_bytes:
                        raise UpdateError("too_large")
                    yield chunk, total
                return
        except httpx.HTTPError as exc:
            log.info("download failed: %s", exc)
            raise UpdateError("download_failed") from exc
    raise UpdateError("download_failed")


def download(
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    client: Optional[httpx.Client] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Download to `dest` and return its SHA-256 (hex). The file appears only
    when complete (written as .partial first); any failure leaves nothing."""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".partial")
    own = client is None
    c = client or _client()
    digest = hashlib.sha256()
    done = 0
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as fh:
            for chunk, total in _iter_download(url, max_bytes, c):
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        os.replace(tmp, dest)
        return digest.hexdigest()
    finally:
        if own:
            c.close()
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def download_text(url: str, max_bytes: int = MAX_SUMS_BYTES, client: Optional[httpx.Client] = None) -> str:
    own = client is None
    c = client or _client()
    try:
        data = b"".join(chunk for chunk, _ in _iter_download(url, max_bytes, c))
    finally:
        if own:
            c.close()
    return data.decode("utf-8", errors="replace")


def fetch_release_sums(version: str, client: Optional[httpx.Client] = None) -> Optional[str]:
    """The SHA256SUMS.txt text of the published release for `version`, or None
    when GitHub has no such release (or it has no checksums). Raises
    UpdateError("release_unreachable") when GitHub can't be reached."""
    own = client is None
    c = client or _client()
    try:
        r = c.get(RELEASE_BY_TAG_URL.format(tag=f"v{version}"),
                  headers={"User-Agent": user_agent(), "Accept": "application/vnd.github+json"})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise UpdateError("release_unreachable")
        rel = parse_release(r.json())
        if rel is None or not rel["sums_url"]:
            return None
        return download_text(rel["sums_url"], client=c)
    except (httpx.HTTPError, ValueError) as exc:
        raise UpdateError("release_unreachable") from exc
    except UpdateError as exc:
        if exc.code in ("download_failed", "host_not_allowed", "too_large"):
            raise UpdateError("release_unreachable") from exc
        raise
    finally:
        if own:
            c.close()


# ---------------------------------------------------------------------------
# Version info of a Setup exe (PE resources), without reading the whole file
# ---------------------------------------------------------------------------
def _read_at(fh, offset: int, size: int) -> bytes:
    fh.seek(offset)
    data = fh.read(size)
    if len(data) != size:
        raise UpdateError("not_an_exe")
    return data


def _pe_version_resource(fh) -> Optional[bytes]:
    """The raw RT_VERSION resource of a PE file, None if it has none. Raises
    UpdateError("not_an_exe") for anything that isn't a well-formed PE."""
    dos = _read_at(fh, 0, 64)
    if dos[:2] != b"MZ":
        raise UpdateError("not_an_exe")
    (lfanew,) = struct.unpack_from("<I", dos, 0x3C)
    if lfanew < 64 or lfanew > 0x1000000:
        raise UpdateError("not_an_exe")
    head = _read_at(fh, lfanew, 24)
    if head[:4] != b"PE\0\0":
        raise UpdateError("not_an_exe")
    _machine, nsec, _ts, _sym, _nsym, opt_size, _chars = struct.unpack_from("<HHIIIHH", head, 4)
    if nsec == 0 or nsec > 96 or opt_size < 96:
        raise UpdateError("not_an_exe")
    opt = _read_at(fh, lfanew + 24, opt_size)
    magic = struct.unpack_from("<H", opt, 0)[0]
    if magic == 0x10B:
        dd = 96
    elif magic == 0x20B:
        dd = 112
    else:
        raise UpdateError("not_an_exe")
    if opt_size < dd + 24 or struct.unpack_from("<I", opt, dd - 4)[0] < 3:
        return None
    rsrc_rva, rsrc_size = struct.unpack_from("<II", opt, dd + 16)
    if not rsrc_rva or not rsrc_size:
        return None
    sections = _read_at(fh, lfanew + 24 + opt_size, 40 * nsec)

    def to_offset(rva: int) -> Optional[int]:
        for i in range(nsec):
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", sections, 40 * i + 8)
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        return None

    base = to_offset(rsrc_rva)
    if base is None:
        return None

    def entries(rel: int) -> list[tuple[int, int]]:
        hdr = _read_at(fh, base + rel, 16)
        named, ids = struct.unpack_from("<HH", hdr, 12)
        if named + ids > 512:
            raise UpdateError("not_an_exe")
        raw = _read_at(fh, base + rel + 16, 8 * (named + ids))
        return [struct.unpack_from("<II", raw, 8 * i) for i in range(named + ids)]

    node = None
    for name, off in entries(0):
        if not name & 0x80000000 and name == 16 and off & 0x80000000:  # RT_VERSION
            node = off & 0x7FFFFFFF
            break
    if node is None:
        return None
    for _ in range(2):  # resource id, then language
        sub = entries(node)
        if not sub:
            return None
        node = sub[0][1]
        if not node & 0x80000000:
            break
        node &= 0x7FFFFFFF
    if node & 0x80000000:
        return None
    rva, size, _cp, _res = struct.unpack("<IIII", _read_at(fh, base + node, 16))
    off = to_offset(rva)
    if off is None or size == 0 or size > 1 << 20:
        return None
    return _read_at(fh, off, size)


def _version_nodes(blob: bytes, start: int, end: int, depth: int = 0):
    """Walk VS_VERSIONINFO nodes: (key, wType, value bytes). Every node is
    wLength, wValueLength, wType, a UTF-16 key, then DWORD-aligned value and
    children."""
    pos = start
    while pos + 6 <= end:
        wlen, wvlen, wtype = struct.unpack_from("<HHH", blob, pos)
        node_end = pos + wlen
        if wlen < 6 or node_end > end:
            return
        k = pos + 6
        while k + 2 <= node_end and blob[k:k + 2] != b"\0\0":
            k += 2
        key = blob[pos + 6:k].decode("utf-16-le", "replace")
        vstart = (k + 2 + 3) & ~3
        vlen = wvlen * 2 if wtype == 1 else wvlen
        yield key, wtype, blob[vstart:vstart + vlen]
        cstart = (vstart + vlen + 3) & ~3
        if depth < 4 and cstart < node_end:
            yield from _version_nodes(blob, cstart, node_end, depth + 1)
        pos = (node_end + 3) & ~3


def read_pe_version(path) -> str:
    """The version a Setup exe says it is: the ProductVersion string (Inno
    stamps the full AppVersion there, so 0.1.0-batch4 survives), else the
    FileVersion string, else the numeric file version. The file name is never
    consulted. Raises UpdateError not_an_exe / no_version."""
    try:
        with open(path, "rb") as fh:
            blob = _pe_version_resource(fh)
    except (OSError, struct.error) as exc:
        raise UpdateError("not_an_exe") from exc
    if blob is None:
        raise UpdateError("no_version")
    strings: dict[str, str] = {}
    fixed: Optional[bytes] = None
    try:
        for key, wtype, value in _version_nodes(blob, 0, len(blob)):
            if key == "VS_VERSION_INFO" and len(value) >= 52 and struct.unpack_from("<I", value, 0)[0] == 0xFEEF04BD:
                fixed = value
            elif wtype == 1 and key in ("ProductVersion", "FileVersion"):
                strings[key] = value.decode("utf-16-le", "replace").rstrip("\0").strip()
    except struct.error as exc:
        raise UpdateError("no_version") from exc
    candidates = [strings.get("ProductVersion"), strings.get("FileVersion")]
    if fixed is not None:
        ms, ls = struct.unpack_from("<II", fixed, 8)
        candidates.append(f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}")
    for c in candidates:
        if c and server_version.VERSION_RE.match(c):
            return c.split("+", 1)[0]
    raise UpdateError("no_version")


# ---------------------------------------------------------------------------
# Trusting an uploaded Setup
# ---------------------------------------------------------------------------
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def authenticode(path) -> tuple[str, str]:
    """(status, signer subject) from Get-AuthenticodeSignature, e.g.
    ("Valid", "CN=..."). Windows only; anywhere else nothing is ever signed."""
    if os.name != "nt":
        return ("NotSupported", "")
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:F7_SIGN_PATH; "
        "$subject = ''; if ($s.SignerCertificate) { $subject = $s.SignerCertificate.Subject }; "
        "[Console]::Out.Write(([string]$s.Status) + '|' + $subject)"
    )
    env = dict(os.environ, F7_SIGN_PATH=str(path))
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=90, env=env, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ("Error", "")
    status, _, subject = (r.stdout or "").partition("|")
    return (status.strip() or "Error", subject.strip())


def _same_subject(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"\s*,\s*", ", ", (s or "").strip()).lower()  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def verify_upload(
    path,
    sha256_hex: str,
    installed: str,
    *,
    fetch_sums: Optional[Callable[[str], Optional[str]]] = None,
    authenticode_fn: Optional[Callable[[object], tuple[str, str]]] = None,
    signer_subject: Optional[str] = None,
) -> dict:
    """Decide whether an uploaded file may be installed. Returns
    {"source": "release"|"signed", "version"} or raises UpdateError.

    The version comes from the exe's own version info. It must be newer than
    `installed`. Then exactly two ways in: the file's SHA-256 is the line for
    F7FIVE0-Setup-<version>.exe in the published release's SHA256SUMS.txt, or it
    has a Valid Authenticode signature whose signer subject equals
    UPDATE_SIGNER_SUBJECT (the empty setting disables that way). Nothing else."""
    version = read_pe_version(path)
    if not is_newer(version, installed):
        raise UpdateError("not_newer")
    signer = settings.update_signer_subject if signer_subject is None else signer_subject
    fetch = fetch_sums or fetch_release_sums
    unreachable = False
    try:
        text = fetch(version)
        if text:
            want = find_sum(text, f"{SETUP_PREFIX}{version}.exe")
            if want and want == sha256_hex.lower():
                return {"source": "release", "version": version}
    except UpdateError as exc:
        if exc.code != "release_unreachable":
            raise
        unreachable = True
    if signer and signer.strip():
        status, subject = (authenticode_fn or authenticode)(path)
        if status == "Valid" and _same_subject(subject, signer):
            return {"source": "signed", "version": version}
    raise UpdateError("release_unreachable" if unreachable else "untrusted_setup")


# --- the admin password step-up ------------------------------------------------
_failures: dict = {}
_failures_lock = threading.Lock()


def reset_password_limiter() -> None:
    with _failures_lock:
        _failures.clear()


def check_admin_password(user_id, password_hash: str, password: str) -> None:
    """Raise unless `password` is this admin's own password. Five wrong tries in
    15 minutes lock the step-up for that admin (a stolen session can't be used
    to guess it). A blank password doesn't count as a try."""
    now = time.monotonic()
    with _failures_lock:
        recent = [t for t in _failures.get(user_id, []) if now - t < PASSWORD_WINDOW_SECONDS]
        _failures[user_id] = recent
        if len(recent) >= MAX_PASSWORD_FAILURES:
            raise UpdateError("too_many_attempts")
    if not password:
        raise UpdateError("admin_password_required")
    if not verify_password(password, password_hash):
        with _failures_lock:
            _failures.setdefault(user_id, []).append(now)
        raise UpdateError("admin_password_incorrect")
    with _failures_lock:
        _failures.pop(user_id, None)


# ---------------------------------------------------------------------------
# The update folder and its files
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def status(self) -> Path:
        return self.root / "status.json"

    @property
    def request(self) -> Path:
        return self.root / "request.json"

    @property
    def incoming(self) -> Path:
        return self.root / "incoming"

    @property
    def setup_cache(self) -> Path:
        return self.root / "setup"


def paths() -> Paths:
    raw = settings.updates_dir.strip()
    return Paths(Path(raw) if raw else _DATA_ROOT / "updates")


def log_path(run_id: str) -> Path:
    return _REPO_ROOT / "logs" / f"update-{run_id}.log"


def max_setup_bytes() -> int:
    return max(1, settings.update_max_setup_mb) * 1024 * 1024


def rollback_ready() -> bool:
    """Is the installed version's own Setup cached, so a failed update can go back?"""
    return (paths().setup_cache / f"{SETUP_PREFIX}{server_version.installed()}.exe").is_file()


def _idle() -> dict:
    return {
        "id": None, "phase": "idle", "active": False, "step": None, "from_version": None,
        "to_version": None, "source": None, "error": None, "error_code": None,
        "started_at": None, "updated_at": None, "finished_at": None,
        "downloaded_bytes": None, "total_bytes": None, "phases": [], "log": [],
    }


def _stale(status: dict, now: Optional[datetime] = None) -> bool:
    updated = ra._parse_time(status.get("updated_at"))
    if updated is None:
        return True
    return ((now or datetime.now(timezone.utc)) - updated).total_seconds() > STALE_AFTER_SECONDS


def run_state(now: Optional[datetime] = None) -> dict:
    """What the admin page shows while (and after) an update happens."""
    status = ra.read_json(paths().status)
    if not status:
        return _idle()
    out = _idle()
    phase = status.get("phase") if isinstance(status.get("phase"), str) else "idle"
    error = status.get("error") if isinstance(status.get("error"), str) else None
    error_code = status.get("error_code") if isinstance(status.get("error_code"), str) else None
    if phase in ACTIVE_PHASES and _stale(status, now):
        error = error or ("The updater didn't start." if phase == "queued" else "The updater stopped responding.")
        error_code = error_code or "updater_stalled"
        phase = "failed"
    run_id = status.get("id") if isinstance(status.get("id"), str) and _RUN_ID_RE.match(status.get("id", "")) else None
    phases = status.get("phases")
    out.update(
        id=run_id, phase=phase, active=phase in ACTIVE_PHASES,
        step=status.get("step") if isinstance(status.get("step"), str) else None,
        from_version=status.get("from_version"), to_version=status.get("to_version"),
        source=status.get("source"), error=ra.redact(error) if error else None, error_code=error_code,
        started_at=status.get("started_at"), updated_at=status.get("updated_at"),
        finished_at=status.get("finished_at"),
        downloaded_bytes=status.get("downloaded_bytes") if isinstance(status.get("downloaded_bytes"), int) else None,
        total_bytes=status.get("total_bytes") if isinstance(status.get("total_bytes"), int) else None,
        phases=[p for p in phases if isinstance(p, str)] if isinstance(phases, list) else [],
        log=ra.read_log_tail(log_path(run_id)) if run_id else [],
    )
    return out


def is_running() -> bool:
    return bool(run_state()["active"])


def clear_incoming() -> None:
    """Remove files left in incoming/ by an earlier run. Only called when no
    update is active."""
    folder = paths().incoming
    if not folder.is_dir():
        return
    for item in folder.iterdir():
        if item.is_file():
            try:
                item.unlink()
            except OSError:
                log.warning("could not remove %s", item)


async def stage_upload(stream: AsyncIterator[bytes], dest_dir: Path, max_bytes: int) -> tuple[Path, str]:
    """Write an upload body to dest_dir/<temp>.partial and return (path,
    sha256). Stops at max_bytes. Called only after the password check, so an
    unauthenticated body is never written."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f"upload-{uuid.uuid4().hex[:12]}.partial"
    digest = hashlib.sha256()
    done = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in stream:
                if not chunk:
                    continue
                done += len(chunk)
                if done > max_bytes:
                    raise UpdateError("too_large")
                fh.write(chunk)
                digest.update(chunk)
        if done == 0:
            raise UpdateError("not_an_exe")
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    return tmp, digest.hexdigest()


def promote_upload(tmp: Path, version: str) -> Path:
    """Give an accepted upload its real name, built from the version its own
    version info reported (never from the name the browser sent)."""
    dest = paths().incoming / f"{SETUP_PREFIX}{version}.exe"
    os.replace(tmp, dest)
    return dest


# --- queueing a run -------------------------------------------------------------
_run_lock = threading.Lock()


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="f7five0-update-download", daemon=True).start()


def get_helper() -> ra.Helper:
    return ra.ScheduledTaskHelper(settings.update_task)


def _write_status(run_id: str, phase: str, **fields) -> None:
    p = paths()
    current = ra.read_json(p.status) or {}
    if current.get("id") != run_id:
        current = {"id": run_id}
    current.update(fields)
    current["phase"] = phase
    current["updated_at"] = _iso()
    phases = [x for x in current.get("phases", []) if isinstance(x, str)]
    if not phases or phases[-1] != phase:
        phases.append(phase)
    current["phases"] = phases
    ra.write_json(p.status, current)


def fail_run(run_id: str, code: str, message: Optional[str] = None) -> None:
    _write_status(run_id, "failed", error=message or MESSAGES.get(code, code), error_code=code, finished_at=_iso(), step=None)


def queue_run(helper: ra.Helper, run_id: str, setup_path: Path, sha256_hex: str, version: str, source: str) -> dict:
    """Write the request, mark the run queued, start the SYSTEM task. The run
    id was reserved by begin_run (or begin_apply)."""
    p = paths()
    try:
        inside = Path(setup_path).resolve().parent == p.incoming.resolve()
    except OSError:
        inside = False
    if not inside:
        raise UpdateError("host_not_allowed")
    ra.write_json(p.request, {
        "id": run_id, "setup_path": str(setup_path), "sha256": sha256_hex.lower(), "version": version, "source": source,
    })
    _write_status(run_id, "queued", step="Starting the updater", error=None, error_code=None)
    try:
        helper.start()
    except ra.HelperError as exc:
        log.warning("update helper did not start: %s", exc)
        try:
            p.request.unlink()
        except FileNotFoundError:
            pass
        fail_run(run_id, "helper_failed")
        raise UpdateError("helper_failed") from exc
    return run_state()


def begin_run(helper: ra.Helper, to_version: str, source: str, first_phase: str = "queued") -> str:
    """Reserve the single update slot: refuse while another run is active and
    write the first status. Returns the run id."""
    if not helper.available():
        raise UpdateError("helper_unavailable")
    with _run_lock:
        if is_running():
            raise UpdateError("update_running")
        run_id = uuid.uuid4().hex
        now = _iso()
        ra.write_json(paths().status, {
            "id": run_id, "phase": first_phase, "from_version": server_version.installed(),
            "to_version": to_version, "source": source, "step": "Starting", "error": None,
            "error_code": None, "started_at": now, "updated_at": now, "finished_at": None,
            "log": str(log_path(run_id)), "phases": [first_phase],
        })
        try:
            paths().request.unlink()
        except FileNotFoundError:
            pass
        return run_id


def begin_apply(db, helper: ra.Helper) -> dict:
    """Install the latest published release: check the stored answer, reserve
    the slot, and download + verify in the background. Raises UpdateError."""
    check = stored_check(db)
    installed = server_version.installed()
    if not helper.available():
        raise UpdateError("helper_unavailable")
    if is_running():
        raise UpdateError("update_running")
    latest = check.get("latest")
    if not latest:
        raise UpdateError("no_update")
    if not is_newer(latest, installed):
        raise UpdateError("not_newer")
    if not check.get("sums_url"):
        raise UpdateError("no_checksums")
    if not check.get("setup_url"):
        raise UpdateError("no_setup")
    run_id = begin_run(helper, latest, "github", first_phase="downloading")
    setup_url, sums_url = check["setup_url"], check["sums_url"]
    _spawn(lambda: _apply_job(helper, run_id, latest, setup_url, sums_url))
    return run_state()


class _Progress:
    """Write download progress to status.json about once a second."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.last = 0.0

    def __call__(self, done: int, total: int) -> None:
        now = time.monotonic()
        if now - self.last < 1.0 and done != total:
            return
        self.last = now
        try:
            _write_status(self.run_id, "downloading", step="Downloading the Setup", downloaded_bytes=done, total_bytes=total or None)
        except OSError:
            pass


def _apply_job(helper: ra.Helper, run_id: str, version: str, setup_url: str, sums_url: str) -> None:
    name = f"{SETUP_PREFIX}{version}.exe"
    try:
        clear_incoming()
        _write_status(run_id, "downloading", step="Fetching the checksum list")
        want = find_sum(download_text(sums_url), name)
        if not want:
            raise UpdateError("no_checksum_line")
        dest = paths().incoming / name
        got = download(setup_url, dest, max_bytes=max_setup_bytes(), on_progress=_Progress(run_id))
        if got != want:
            try:
                dest.unlink()
            except FileNotFoundError:
                pass
            raise UpdateError("hash_mismatch")
        queue_run(helper, run_id, dest, got, version, "github")
    except UpdateError as exc:
        if exc.code != "helper_failed":  # queue_run already recorded that one
            fail_run(run_id, exc.code, exc.message)
        clear_incoming()
    except Exception:
        log.exception("update download raised")
        fail_run(run_id, "download_failed")
        clear_incoming()
