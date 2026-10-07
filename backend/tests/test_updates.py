"""Server self-update: version compare, GitHub release parsing, the download
allowlist, both upload trust paths, the admin password step-up, downgrade
refusal, and the request/status protocol with the SYSTEM updater task.

Nothing here touches the network or a real installer: GitHub is an
httpx.MockTransport, the Authenticode check is stubbed, and the scheduled
task helper is a fake. Setup "exes" are tiny hand-built PE files.
"""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
import pytest

from app import scheduler
from app.api import admin as admin_routes
from app.api.deps import current_user, require_admin
from app.config import settings
from app.main import app
from app.models.user import User
from app.services import app_settings, remote_access as ra, server_version, updates
from app.services.security import hash_password

ADMIN_PW = "correct horse battery staple"
SETUP_BYTES_PAD = b"F7FIVE0 test setup payload " * 64


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------
@pytest.fixture()
def upd_dir(tmp_path, monkeypatch):
    """Updates folder, version file, and the knobs the tests turn."""
    folder = tmp_path / "updates"
    monkeypatch.setattr(settings, "updates_dir", str(folder))
    vfile = tmp_path / "version.json"
    vfile.write_text(json.dumps({"version": "1.0.0", "installed_at": "2026-10-01T00:00:00Z"}))
    monkeypatch.setattr(settings, "server_version_file", str(vfile))
    monkeypatch.setattr(settings, "update_signer_subject", "")
    monkeypatch.setattr(settings, "update_max_setup_mb", 50)
    return folder


@pytest.fixture(autouse=True)
def _reset_limiter():
    updates.reset_password_limiter()
    yield
    updates.reset_password_limiter()


class FakeHelper:
    def __init__(self, available: bool = True, fail: bool = False):
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
def helper(client):
    h = FakeHelper()
    app.dependency_overrides[admin_routes.get_update_helper] = lambda: h
    return h


@pytest.fixture()
def admin_pw(client):
    admin = app.dependency_overrides[current_user]()
    admin.password_hash = hash_password(ADMIN_PW)
    return ADMIN_PW


@pytest.fixture()
def inline(monkeypatch):
    """Run the background download inline so the test sees its result."""
    monkeypatch.setattr(updates, "_spawn", lambda fn: fn())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- a minimal PE with a version resource ------------------------------------
def _align4(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)


def _node(key: str, value: bytes, children: bytes, wtype: int, value_len: int) -> bytes:
    key_b = (key + "\0").encode("utf-16-le")
    body = _align4(struct.pack("<HHH", 0, value_len, wtype) + key_b) + value
    body = _align4(body) + children
    return struct.pack("<H", len(body)) + body[2:]


def _string(key: str, text: str) -> bytes:
    return _node(key, (text + "\0").encode("utf-16-le"), b"", 1, len(text) + 1)


def version_blob(product_text: Optional[str], file_version=(1, 2, 0, 0)) -> bytes:
    strings = b""
    if product_text is not None:
        strings += _align4(_string("CompanyName", "F7FIVE0"))
        strings += _align4(_string("ProductVersion", product_text))
    table = _node("040904B0", b"", strings, 1, 0)
    info = _node("StringFileInfo", b"", _align4(table), 1, 0)
    a, b, c, d = file_version
    fixed = struct.pack(
        "<13I", 0xFEEF04BD, 0x00010000, (a << 16) | b, (c << 16) | d,
        (a << 16) | b, (c << 16) | d, 0x3F, 0, 4, 1, 0, 0, 0,
    )
    return _node("VS_VERSION_INFO", fixed, _align4(info), 0, len(fixed))


def _dir(n_id: int) -> bytes:
    return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, n_id)


def make_exe(version_resource: Optional[bytes], padding: int = 0) -> bytes:
    """A PE32+ image with a single .rsrc section carrying RT_VERSION."""
    rva = 0x1000
    rsrc = b""
    if version_resource is not None:
        data_off = 88
        rsrc = (
            _dir(1) + struct.pack("<II", 16, 0x80000000 | 24)
            + _dir(1) + struct.pack("<II", 1, 0x80000000 | 48)
            + _dir(1) + struct.pack("<II", 0x409, 72)
            + struct.pack("<IIII", rva + data_off, len(version_resource), 0, 0)
            + version_resource
        )
    raw = rsrc + b"\0" * (-len(rsrc) % 0x200 or 0)
    if not raw:
        raw = b"\0" * 0x200
    dos = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x80)
    dos = dos + b"\0" * (0x80 - len(dos))
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 0xF0, 0x0022)
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)
    struct.pack_into("<I", opt, 108, 16)
    if version_resource is not None:
        struct.pack_into("<II", opt, 112 + 16, rva, len(rsrc))
    section = (
        b".rsrc\0\0\0" + struct.pack("<IIIIIIHHI", len(rsrc), rva, len(raw), 0x200, 0, 0, 0, 0, 0x40000040)
    )
    headers = dos + b"PE\0\0" + coff + bytes(opt) + section
    headers = headers + b"\0" * (0x200 - len(headers))
    return headers + raw + b"X" * padding


def setup_exe(version: str = "1.1.0", *, text: bool = True) -> bytes:
    parts = [int(p) for p in version.split("-")[0].split(".")] + [0]
    return make_exe(version_blob(version if text else None, tuple(parts[:4])), padding=2048)


# -- GitHub ------------------------------------------------------------------
def release_payload(tag="v1.1.0", *, draft=False, prerelease=False, sums=True, setup=True) -> dict:
    version = tag.lstrip("v")
    base = f"https://github.com/jonfuego/F7FIVE0/releases/download/{tag}"
    assets = [{"name": f"F7FIVE0-{version}.zip", "browser_download_url": f"{base}/F7FIVE0-{version}.zip", "size": 9}]
    if setup:
        assets.append({"name": f"F7FIVE0-Setup-{version}.exe", "browser_download_url": f"{base}/F7FIVE0-Setup-{version}.exe", "size": 100})
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/SHA256SUMS.txt", "size": 200})
    return {"tag_name": tag, "name": tag, "body": "What changed\n- one thing\n- another", "draft": draft,
            "prerelease": prerelease, "assets": assets}


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def github_handler(payload: Optional[dict], seen: Optional[list] = None, files: Optional[dict] = None):
    files = files or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        url = str(request.url)
        if url == updates.RELEASES_LATEST_URL:
            return httpx.Response(200, json=payload) if payload is not None else httpx.Response(404, json={"message": "Not Found"})
        if url in files:
            return files[url]
        return httpx.Response(404)

    return handler


def stored_check(version="1.1.0", *, sums=True) -> dict:
    p = release_payload(f"v{version}", sums=sums)
    rel = updates.parse_release(p)
    return {"checked_at": "2026-10-07T12:00:00Z", "latest": rel["version"], "notes": rel["notes"],
            "setup_url": rel["setup_url"], "sums_url": rel["sums_url"], "error": None}


# ---------------------------------------------------------------------------
# Version compare (semver)
# ---------------------------------------------------------------------------
def test_semver_orders_prerelease_below_release():
    assert updates.compare_versions("0.1.0-batch4", "0.1.0") < 0
    assert updates.compare_versions("0.1.0", "0.1.0-batch4") > 0
    assert updates.compare_versions("1.0.0", "1.0.0") == 0
    assert updates.compare_versions("v1.0.1", "1.0.0") > 0
    assert updates.compare_versions("0.0.0-dev", "0.0.1") < 0


def test_semver_numeric_parts_are_numbers_not_text():
    assert updates.compare_versions("1.10.0", "1.9.0") > 0
    assert updates.compare_versions("1.2.10", "1.2.9") > 0
    assert updates.compare_versions("2.0.0", "1.99.99") > 0


def test_semver_prerelease_identifier_rules():
    order = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
             "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
    for lower, higher in zip(order, order[1:]):
        assert updates.compare_versions(lower, higher) < 0, (lower, higher)
        assert updates.compare_versions(higher, lower) > 0, (higher, lower)


@pytest.mark.parametrize("text", ["", "1", "1.2", "1.2.3.4", "a.b.c", "1.2.3-", "1.2.3 beta", None, "01.2.3"])
def test_parse_version_rejects_junk(text):
    assert updates.parse_version(text) is None


def test_is_newer_needs_strictly_greater():
    assert updates.is_newer("1.1.0", "1.0.0") is True
    assert updates.is_newer("1.0.0", "1.0.0") is False
    assert updates.is_newer("1.0.0", "1.1.0") is False
    assert updates.is_newer("1.0.0", "1.0.0-batch4") is True
    assert updates.is_newer(None, "1.0.0") is False
    assert updates.is_newer("garbage", "1.0.0") is False


# ---------------------------------------------------------------------------
# Release parsing
# ---------------------------------------------------------------------------
def test_parse_release_takes_tag_notes_and_assets():
    rel = updates.parse_release(release_payload("v1.2.3"))
    assert rel["version"] == "1.2.3" and rel["tag"] == "v1.2.3"
    assert rel["notes"].startswith("What changed")
    assert rel["setup_url"].endswith("/v1.2.3/F7FIVE0-Setup-1.2.3.exe")
    assert rel["sums_url"].endswith("/v1.2.3/SHA256SUMS.txt")


def test_parse_release_skips_drafts_and_prereleases():
    assert updates.parse_release(release_payload(draft=True)) is None
    assert updates.parse_release(release_payload(prerelease=True)) is None
    assert updates.parse_release(release_payload("v1.2.0-rc1")) is None


def test_parse_release_without_checksums_or_setup():
    no_sums = updates.parse_release(release_payload(sums=False))
    assert no_sums["version"] == "1.1.0" and no_sums["sums_url"] is None and no_sums["setup_url"]
    no_setup = updates.parse_release(release_payload(setup=False))
    assert no_setup["setup_url"] is None


@pytest.mark.parametrize("payload", [None, {}, [], {"tag_name": "nightly", "assets": []}, {"tag_name": 5}])
def test_parse_release_ignores_odd_payloads(payload):
    assert updates.parse_release(payload) is None


def test_find_sum_matches_the_exact_file_name():
    good = "a" * 64
    other = "b" * 64
    text = (
        f"{other}  F7FIVE0-1.1.0.zip\n"
        f"{good.upper()} *F7FIVE0-Setup-1.1.0.exe\n"
        f"{other}  F7FIVE0-Setup-1.1.0.exe.sig\n"
        "not a checksum line\n"
    )
    assert updates.find_sum(text, "F7FIVE0-Setup-1.1.0.exe") == good
    assert updates.find_sum(text, "F7FIVE0-Setup-9.9.9.exe") is None
    assert updates.find_sum(text, "Setup-1.1.0.exe") is None
    assert updates.find_sum("", "F7FIVE0-Setup-1.1.0.exe") is None


# ---------------------------------------------------------------------------
# The check: GitHub in, update_check out
# ---------------------------------------------------------------------------
def test_check_stores_the_latest_release(db_session):
    seen: list = []
    c = mock_client(github_handler(release_payload("v1.1.0"), seen))
    result = updates.check_for_update(db_session, client=c)
    assert set(result) == {"checked_at", "latest", "notes", "setup_url", "sums_url", "error"}
    assert result["latest"] == "1.1.0" and result["error"] is None
    assert result["sums_url"].endswith("SHA256SUMS.txt")
    assert app_settings.get(db_session, "update_check") == result
    req = seen[0]
    assert "F7FIVE0" in req.headers["user-agent"]
    assert "authorization" not in req.headers  # public repo, no token


def test_check_network_error_is_stored_never_raised(db_session):
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))

    def boom(request):
        raise httpx.ConnectError("no route to host")

    result = updates.check_for_update(db_session, client=mock_client(boom))
    assert result["error"] and "reach" in result["error"].lower()
    assert result["latest"] == "1.1.0"  # last known answer stays
    assert app_settings.get(db_session, "update_check")["error"] == result["error"]


def test_check_rate_limit_is_stored(db_session):
    c = mock_client(lambda r: httpx.Response(403, json={"message": "API rate limit exceeded"}))
    result = updates.check_for_update(db_session, client=c)
    assert result["error"] and "rate" in result["error"].lower()


def test_check_with_no_release_yet(db_session):
    result = updates.check_for_update(db_session, client=mock_client(github_handler(None)))
    assert result["latest"] is None and result["error"]


def test_check_never_offers_a_prerelease_or_draft(db_session):
    c = mock_client(github_handler(release_payload("v2.0.0", prerelease=True)))
    result = updates.check_for_update(db_session, client=c)
    assert result["latest"] is None and result["error"]


# ---------------------------------------------------------------------------
# Downloads: host allowlist and size cap
# ---------------------------------------------------------------------------
def test_download_refuses_hosts_outside_the_allowlist(tmp_path):
    c = mock_client(lambda r: httpx.Response(200, content=b"x"))
    for url in ("https://evil.example.com/F7FIVE0-Setup-1.1.0.exe",
                "https://github.com.evil.example/x.exe",
                "https://notgithub.com/x.exe",
                "https://api.github.com/x.exe"):
        with pytest.raises(updates.UpdateError) as e:
            updates.download(url, tmp_path / "x.exe", max_bytes=1000, client=c)
        assert e.value.code == "host_not_allowed", url
    assert not (tmp_path / "x.exe").exists()


def test_download_refuses_plain_http_and_redirects_off_the_allowlist(tmp_path):
    c = mock_client(lambda r: httpx.Response(200, content=b"x"))
    with pytest.raises(updates.UpdateError) as e:
        updates.download("http://github.com/x.exe", tmp_path / "a.exe", max_bytes=1000, client=c)
    assert e.value.code == "host_not_allowed"

    def redirect(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"location": "https://evil.example.com/steal.exe"})
        return httpx.Response(200, content=b"x")

    with pytest.raises(updates.UpdateError) as e:
        updates.download("https://github.com/x.exe", tmp_path / "b.exe", max_bytes=1000, client=mock_client(redirect))
    assert e.value.code == "host_not_allowed"
    assert not (tmp_path / "b.exe").exists()


def test_download_follows_github_redirects_and_returns_the_hash(tmp_path):
    body = b"setup bytes " * 100
    hops = []

    def handler(request):
        hops.append(request.url.host)
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"location": "https://release-assets.githubusercontent.com/abc/def"})
        if request.url.host == "release-assets.githubusercontent.com":
            return httpx.Response(302, headers={"location": "https://objects.githubusercontent.com/zzz"})
        return httpx.Response(200, content=body, headers={"content-length": str(len(body))})

    seen = []
    digest = updates.download(
        "https://github.com/jonfuego/F7FIVE0/releases/download/v1.1.0/F7FIVE0-Setup-1.1.0.exe",
        tmp_path / "ok.exe", max_bytes=10_000, client=mock_client(handler),
        on_progress=lambda done, total: seen.append((done, total)),
    )
    assert hops == ["github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"]
    assert digest == sha(body) and (tmp_path / "ok.exe").read_bytes() == body
    assert seen and seen[-1][0] == len(body)
    assert not list(tmp_path.glob("*.partial"))


def test_download_enforces_the_size_cap(tmp_path):
    big = b"y" * 5000
    # Declared length over the cap: refused before reading the body.
    c = mock_client(lambda r: httpx.Response(200, content=big, headers={"content-length": "5000"}))
    with pytest.raises(updates.UpdateError) as e:
        updates.download("https://github.com/a.exe", tmp_path / "a.exe", max_bytes=1000, client=c)
    assert e.value.code == "too_large"
    # No honest length: cut off while streaming.
    chunked = mock_client(lambda r: httpx.Response(200, content=iter([big[:600], big[600:1200], big[1200:]])))
    with pytest.raises(updates.UpdateError) as e:
        updates.download("https://github.com/b.exe", tmp_path / "b.exe", max_bytes=1000, client=chunked)
    assert e.value.code == "too_large"
    assert not (tmp_path / "a.exe").exists() and not (tmp_path / "b.exe").exists()
    assert not list(tmp_path.glob("*.partial"))


# ---------------------------------------------------------------------------
# Version info from the exe
# ---------------------------------------------------------------------------
def test_pe_version_prefers_the_product_text_version(tmp_path):
    p = tmp_path / "F7FIVE0-Setup-whatever.exe"
    p.write_bytes(setup_exe("0.1.0-batch4"))
    assert updates.read_pe_version(p) == "0.1.0-batch4"


def test_pe_version_falls_back_to_the_numeric_file_version(tmp_path):
    p = tmp_path / "x.exe"
    p.write_bytes(make_exe(version_blob(None, (2, 3, 4, 0))))
    assert updates.read_pe_version(p) == "2.3.4"


def test_pe_version_errors(tmp_path):
    notpe = tmp_path / "a.exe"
    notpe.write_bytes(b"#!/bin/sh\necho hi\n" * 50)
    with pytest.raises(updates.UpdateError) as e:
        updates.read_pe_version(notpe)
    assert e.value.code == "not_an_exe"
    truncated = tmp_path / "b.exe"
    truncated.write_bytes(setup_exe()[:100])
    with pytest.raises(updates.UpdateError) as e:
        updates.read_pe_version(truncated)
    assert e.value.code == "not_an_exe"
    noversion = tmp_path / "c.exe"
    noversion.write_bytes(make_exe(None))
    with pytest.raises(updates.UpdateError) as e:
        updates.read_pe_version(noversion)
    assert e.value.code == "no_version"


# ---------------------------------------------------------------------------
# Upload trust: a release hash, or an F7FIVE0 signature, nothing else
# ---------------------------------------------------------------------------
def _staged(tmp_path, version="1.1.0") -> tuple[Path, str]:
    data = setup_exe(version)
    p = tmp_path / "upload.partial"
    p.write_bytes(data)
    return p, sha(data)


def _sums_for(digest: str, version="1.1.0"):
    return lambda v: f"{digest}  F7FIVE0-Setup-{version}.exe\n"


def test_upload_accepted_when_it_matches_the_published_release_hash(tmp_path):
    p, digest = _staged(tmp_path)
    got = updates.verify_upload(p, digest, "1.0.0", fetch_sums=_sums_for(digest))
    assert got == {"source": "release", "version": "1.1.0"}


def test_upload_refused_when_unsigned_and_not_a_release_build(tmp_path):
    p, digest = _staged(tmp_path)
    other = _sums_for("0" * 64)
    with pytest.raises(updates.UpdateError) as e:
        updates.verify_upload(p, digest, "1.0.0", fetch_sums=other,
                              authenticode_fn=lambda path: ("NotSigned", ""), signer_subject="")
    assert e.value.code == "untrusted_setup"
    assert "published" in e.value.message.lower()


def test_upload_accepted_with_a_valid_signature_from_the_configured_signer(tmp_path):
    p, digest = _staged(tmp_path)
    subject = "CN=F7FIVE0 Release, O=F7FIVE0, C=US"
    got = updates.verify_upload(
        p, digest, "1.0.0", fetch_sums=_sums_for("0" * 64),
        authenticode_fn=lambda path: ("Valid", subject), signer_subject=subject,
    )
    assert got == {"source": "signed", "version": "1.1.0"}


@pytest.mark.parametrize("status,subject", [
    ("Valid", "CN=Someone Else, O=Evil, C=US"),
    ("HashMismatch", "CN=F7FIVE0 Release, O=F7FIVE0, C=US"),
    ("NotSigned", ""),
    ("UnknownError", "CN=F7FIVE0 Release, O=F7FIVE0, C=US"),
])
def test_upload_signature_must_be_valid_and_from_the_signer(tmp_path, status, subject):
    p, digest = _staged(tmp_path)
    with pytest.raises(updates.UpdateError) as e:
        updates.verify_upload(
            p, digest, "1.0.0", fetch_sums=_sums_for("0" * 64),
            authenticode_fn=lambda path: (status, subject),
            signer_subject="CN=F7FIVE0 Release, O=F7FIVE0, C=US",
        )
    assert e.value.code == "untrusted_setup"


def test_empty_signer_setting_switches_the_signature_path_off(tmp_path):
    p, digest = _staged(tmp_path)
    calls = []

    def sig(path):
        calls.append(path)
        return ("Valid", "CN=F7FIVE0 Release, O=F7FIVE0, C=US")

    with pytest.raises(updates.UpdateError) as e:
        updates.verify_upload(p, digest, "1.0.0", fetch_sums=_sums_for("0" * 64),
                              authenticode_fn=sig, signer_subject="")
    assert e.value.code == "untrusted_setup" and calls == []


def test_upload_that_cannot_reach_github_says_so(tmp_path):
    p, digest = _staged(tmp_path)

    def offline(version):
        raise updates.UpdateError("release_unreachable")

    with pytest.raises(updates.UpdateError) as e:
        updates.verify_upload(p, digest, "1.0.0", fetch_sums=offline, signer_subject="")
    assert e.value.code == "release_unreachable"


def test_upload_refuses_the_same_or_a_lower_version(tmp_path):
    p, digest = _staged(tmp_path, "1.1.0")
    for installed in ("1.1.0", "1.2.0", "2.0.0"):
        with pytest.raises(updates.UpdateError) as e:
            updates.verify_upload(p, digest, installed, fetch_sums=_sums_for(digest))
        assert e.value.code == "not_newer", installed
    # A prerelease of the same number is lower than the release.
    p2, d2 = _staged(tmp_path, "0.1.0-batch4")
    with pytest.raises(updates.UpdateError) as e:
        updates.verify_upload(p2, d2, "0.1.0", fetch_sums=_sums_for(d2, "0.1.0-batch4"))
    assert e.value.code == "not_newer"


def test_upload_uses_the_exe_version_not_the_file_name(tmp_path):
    data = setup_exe("1.1.0")
    p = tmp_path / "F7FIVE0-Setup-9.9.9.exe"
    p.write_bytes(data)
    got = updates.verify_upload(p, sha(data), "1.0.0", fetch_sums=_sums_for(sha(data)))
    assert got["version"] == "1.1.0"


# ---------------------------------------------------------------------------
# Installed version and /api/health
# ---------------------------------------------------------------------------
def test_server_version_reads_setup_record_with_a_fallback(tmp_path, monkeypatch):
    f = tmp_path / "version.json"
    monkeypatch.setattr(settings, "server_version_file", str(f))
    assert server_version.installed() == "0.0.0-dev"  # no file
    f.write_text("not json")
    assert server_version.installed() == "0.0.0-dev"
    f.write_text(json.dumps({"version": "not a version"}))
    assert server_version.installed() == "0.0.0-dev"
    f.write_text(json.dumps({"version": "1.4.2", "installed_at": "2026-10-07T00:00:00Z"}))
    assert server_version.installed() == "1.4.2"
    f.write_text("\ufeff" + json.dumps({"version": "1.5.0-rc.1"}), encoding="utf-8")  # PowerShell 5.1 writes a BOM
    assert server_version.installed() == "1.5.0-rc.1"


def test_health_reports_the_installed_version(client, upd_dir):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["version"] == "1.0.0"
    assert r.json()["version"] != "0.1.0"
    assert app.version != "0.1.0"  # the FastAPI app version is no longer hard-coded


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
def test_updates_overview_shape(client, db_session, upd_dir, helper, monkeypatch):
    from app.services import android_app
    apk = android_app.Apk(path=Path("F7FIVE0-1.0.1.apk"), version="1.0.1", abi="arm64")
    monkeypatch.setattr(android_app, "find_apks", lambda folder=None: {"arm64": apk})
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    r = client.get("/api/admin/updates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["installed_version"] == "1.0.0"
    assert body["phone_app_version"] == "1.0.1"
    assert body["latest_version"] == "1.1.0" and body["update_available"] is True
    assert body["can_install"] is True and body["install_blocked"] is None
    assert body["notes"].startswith("What changed")
    assert body["checked_at"] and body["check_error"] is None
    assert body["helper_available"] is True
    assert body["signer_configured"] is False
    assert body["run"]["phase"] == "idle"
    assert "setup_url" not in body and "secret" not in json.dumps(body)


def test_updates_overview_when_current_or_missing_checksums(client, db_session, upd_dir, helper):
    app_settings.put(db_session, "update_check", stored_check("1.0.0"))
    assert client.get("/api/admin/updates").json()["update_available"] is False
    app_settings.put(db_session, "update_check", stored_check("1.1.0", sums=False))
    body = client.get("/api/admin/updates").json()
    assert body["update_available"] is True and body["can_install"] is False
    assert body["install_blocked"] == "no_checksums"


def test_check_endpoint_runs_a_check_and_stores_it(client, db_session, upd_dir, helper, monkeypatch):
    monkeypatch.setattr(updates, "_client", lambda: mock_client(github_handler(release_payload("v1.3.0"))))
    r = client.post("/api/admin/updates/check")
    assert r.status_code == 200, r.text
    assert r.json()["latest_version"] == "1.3.0" and r.json()["update_available"] is True
    assert app_settings.get(db_session, "update_check")["latest"] == "1.3.0"


def test_badge_shows_only_when_a_newer_release_is_waiting(client, db_session, upd_dir):
    assert client.get("/api/admin/updates/badge").json() == {"update_available": False, "latest_version": None}
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    assert client.get("/api/admin/updates/badge").json() == {"update_available": True, "latest_version": "1.1.0"}
    app_settings.put(db_session, "update_check", stored_check("1.0.0"))  # installed is 1.0.0
    assert client.get("/api/admin/updates/badge").json()["update_available"] is False
    vfile = Path(settings.server_version_file)
    vfile.write_text(json.dumps({"version": "0.9.0"}))  # fake an older install
    assert client.get("/api/admin/updates/badge").json()["update_available"] is True


def test_check_endpoint_is_admin_only(client, db_session, upd_dir):
    member = User(username="member1", display_name="M", password_hash="x", role="member", is_active=True)
    db_session.add(member)
    db_session.flush()
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides[current_user] = lambda: member
    assert client.post("/api/admin/updates/check").status_code == 403
    assert client.get("/api/admin/updates").status_code == 403
    assert client.get("/api/admin/updates/badge").status_code == 403
    assert client.post("/api/admin/updates/apply").status_code == 403
    assert client.post("/api/admin/updates/upload", content=b"x").status_code == 403


# -- upload route -------------------------------------------------------------
def _upload(client, data: bytes, password: Optional[str] = ADMIN_PW, **extra):
    headers = {"content-type": "application/octet-stream"}
    if password is not None:
        headers["x-confirm-password"] = password
    headers.update(extra)
    return client.post("/api/admin/updates/upload", content=data, headers=headers)


def _incoming(upd_dir: Path) -> list[str]:
    d = upd_dir / "incoming"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def test_upload_without_the_admin_password_is_refused(client, upd_dir, helper, admin_pw):
    r = _upload(client, setup_exe(), password=None)
    assert r.status_code in (401, 403) and r.json()["detail"] == "admin_password_required"
    assert helper.started == 0 and _incoming(upd_dir) == []


def test_upload_with_the_wrong_password_is_refused(client, upd_dir, helper, admin_pw):
    r = _upload(client, setup_exe(), password="not the password")
    assert r.status_code == 403 and r.json()["detail"] == "admin_password_incorrect"
    assert helper.started == 0 and _incoming(upd_dir) == []


def test_upload_password_is_checked_before_the_file_is_kept(client, upd_dir, helper, admin_pw, monkeypatch):
    kept = []
    real = updates.stage_upload

    async def spy(*a, **kw):
        kept.append(1)
        return await real(*a, **kw)

    monkeypatch.setattr(updates, "stage_upload", spy)
    _upload(client, setup_exe(), password="nope")
    assert kept == []  # the body was never read or written


def test_upload_password_may_use_non_ascii_characters(client, upd_dir, helper, db_session, monkeypatch):
    from urllib.parse import quote
    admin = app.dependency_overrides[current_user]()
    admin.password_hash = hash_password("p\u00e4ssw\u00f6rd-\u00fcn\u00ef")
    data = setup_exe()
    monkeypatch.setattr(updates, "fetch_release_sums", lambda v, client=None: f"{sha(data)}  F7FIVE0-Setup-{v}.exe\n")
    r = _upload(client, data, password=quote("p\u00e4ssw\u00f6rd-\u00fcn\u00ef", safe=""))
    assert r.status_code == 202, r.text


def test_upload_password_guessing_is_throttled(client, upd_dir, helper, admin_pw):
    for _ in range(updates.MAX_PASSWORD_FAILURES):
        assert _upload(client, b"x", password="wrong").status_code == 403
    r = _upload(client, b"x", password=ADMIN_PW)
    assert r.status_code == 429 and r.json()["detail"] == "too_many_attempts"


def test_upload_of_an_unknown_unsigned_exe_is_refused(client, upd_dir, helper, admin_pw, monkeypatch):
    monkeypatch.setattr(updates, "fetch_release_sums", lambda v, client=None: f"{'0' * 64}  F7FIVE0-Setup-{v}.exe\n")
    monkeypatch.setattr(updates, "authenticode", lambda path: ("NotSigned", ""))
    r = _upload(client, setup_exe("1.1.0"))
    assert r.status_code == 403 and r.json()["detail"] == "untrusted_setup"
    assert helper.started == 0
    assert _incoming(upd_dir) == []  # refused files are not kept
    assert not (upd_dir / "request.json").exists()


def test_upload_that_matches_the_release_hash_is_accepted_and_starts_the_update(client, upd_dir, helper, admin_pw, monkeypatch, db_session):
    data = setup_exe("1.1.0")
    monkeypatch.setattr(updates, "fetch_release_sums", lambda v, client=None: f"{sha(data)}  F7FIVE0-Setup-{v}.exe\n")
    r = _upload(client, data, **{"x-file-name": "totally-renamed.exe"})
    assert r.status_code == 202, r.text
    assert r.json()["phase"] == "queued" and r.json()["to_version"] == "1.1.0"
    assert helper.started == 1
    req = json.loads((upd_dir / "request.json").read_text(encoding="utf-8"))
    assert set(req) == {"id", "setup_path", "sha256", "version", "source"}
    assert req["source"] == "release" and req["version"] == "1.1.0" and req["sha256"] == sha(data)
    staged = Path(req["setup_path"])
    assert staged.parent == (upd_dir / "incoming") and staged.name == "F7FIVE0-Setup-1.1.0.exe"
    assert staged.read_bytes() == data
    assert json.loads((upd_dir / "status.json").read_text(encoding="utf-8"))["phase"] == "queued"


def test_upload_signed_by_the_configured_signer_is_accepted(client, upd_dir, helper, admin_pw, monkeypatch):
    subject = "CN=F7FIVE0 Release, O=F7FIVE0, C=US"
    monkeypatch.setattr(settings, "update_signer_subject", subject)
    monkeypatch.setattr(updates, "fetch_release_sums", lambda v, client=None: None)
    monkeypatch.setattr(updates, "authenticode", lambda path: ("Valid", subject))
    r = _upload(client, setup_exe("1.1.0"))
    assert r.status_code == 202, r.text
    assert json.loads((upd_dir / "request.json").read_text(encoding="utf-8"))["source"] == "signed"


def test_upload_over_the_size_cap_is_refused(client, upd_dir, helper, admin_pw, monkeypatch):
    monkeypatch.setattr(settings, "update_max_setup_mb", 1)
    r = _upload(client, setup_exe("1.1.0") + b"Z" * (2 * 1024 * 1024))
    assert r.status_code == 413 and r.json()["detail"] == "too_large"
    assert _incoming(upd_dir) == [] and helper.started == 0


def test_upload_that_is_not_an_exe_is_refused(client, upd_dir, helper, admin_pw):
    r = _upload(client, b"just some text " * 100)
    assert r.status_code == 400 and r.json()["detail"] == "not_an_exe"
    assert _incoming(upd_dir) == []


def test_upload_downgrade_is_refused(client, upd_dir, helper, admin_pw, monkeypatch):
    data = setup_exe("0.9.0")
    monkeypatch.setattr(updates, "fetch_release_sums", lambda v, client=None: f"{sha(data)}  F7FIVE0-Setup-{v}.exe\n")
    r = _upload(client, data)
    assert r.status_code == 409 and r.json()["detail"] == "not_newer"
    assert helper.started == 0 and _incoming(upd_dir) == []


def test_upload_while_an_update_is_running_is_refused(client, upd_dir, helper, admin_pw, monkeypatch):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (upd_dir).mkdir(parents=True)
    (upd_dir / "status.json").write_text(json.dumps({"id": "a" * 32, "phase": "installing", "updated_at": now}))
    r = _upload(client, setup_exe("1.1.0"))
    assert r.status_code == 409 and r.json()["detail"] == "update_running"


# -- apply from GitHub ----------------------------------------------------------
SETUP_FILE = b"MZ-fake-setup-for-download " * 40


def _apply_files(good_hash: str, setup_host="github.com"):
    base = "https://github.com/jonfuego/F7FIVE0/releases/download/v1.1.0"
    cdn = "https://release-assets.githubusercontent.com/blob"
    return {
        f"{base}/F7FIVE0-Setup-1.1.0.exe": httpx.Response(302, headers={"location": f"{cdn}/setup"}),
        f"{cdn}/setup": httpx.Response(200, content=SETUP_FILE, headers={"content-length": str(len(SETUP_FILE))}),
        f"{base}/SHA256SUMS.txt": httpx.Response(200, text=f"{good_hash}  F7FIVE0-Setup-1.1.0.exe\n{'c' * 64}  F7FIVE0-1.1.0.zip\n"),
    }


def _wire(monkeypatch, files):
    monkeypatch.setattr(updates, "_client", lambda: mock_client(github_handler(None, files=files)))


def test_apply_downloads_verifies_and_starts_the_update(client, db_session, upd_dir, helper, inline, monkeypatch):
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    _wire(monkeypatch, _apply_files(sha(SETUP_FILE)))
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 202, r.text
    assert helper.started == 1
    req = json.loads((upd_dir / "request.json").read_text(encoding="utf-8"))
    assert req["source"] == "github" and req["version"] == "1.1.0" and req["sha256"] == sha(SETUP_FILE)
    assert Path(req["setup_path"]).read_bytes() == SETUP_FILE
    assert Path(req["setup_path"]).parent == upd_dir / "incoming"
    assert client.get("/api/admin/updates/run").json()["phase"] == "queued"


def test_apply_refuses_a_setup_that_does_not_match_its_checksum(client, db_session, upd_dir, helper, inline, monkeypatch):
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    _wire(monkeypatch, _apply_files("d" * 64))
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 202  # accepted, then fails in the background
    run = client.get("/api/admin/updates/run").json()
    assert run["phase"] == "failed" and run["error_code"] == "hash_mismatch"
    assert helper.started == 0
    assert not (upd_dir / "request.json").exists()
    assert _incoming(upd_dir) == []


def test_apply_refuses_a_setup_without_a_checksum_line(client, db_session, upd_dir, helper, inline, monkeypatch):
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    files = _apply_files(sha(SETUP_FILE))
    base = "https://github.com/jonfuego/F7FIVE0/releases/download/v1.1.0"
    files[f"{base}/SHA256SUMS.txt"] = httpx.Response(200, text=f"{'c' * 64}  F7FIVE0-1.1.0.zip\n")
    _wire(monkeypatch, files)
    client.post("/api/admin/updates/apply")
    run = client.get("/api/admin/updates/run").json()
    assert run["phase"] == "failed" and run["error_code"] == "no_checksum_line"
    assert helper.started == 0 and not (upd_dir / "request.json").exists()


def test_apply_refuses_a_download_host_outside_the_allowlist(client, db_session, upd_dir, helper, inline, monkeypatch):
    check = stored_check("1.1.0")
    check["setup_url"] = "https://evil.example.com/F7FIVE0-Setup-1.1.0.exe"
    app_settings.put(db_session, "update_check", check)
    _wire(monkeypatch, _apply_files(sha(SETUP_FILE)))
    client.post("/api/admin/updates/apply")
    run = client.get("/api/admin/updates/run").json()
    assert run["phase"] == "failed" and run["error_code"] == "host_not_allowed"
    assert helper.started == 0 and _incoming(upd_dir) == []


def test_apply_refuses_a_release_that_has_no_checksums(client, db_session, upd_dir, helper, inline):
    app_settings.put(db_session, "update_check", stored_check("1.1.0", sums=False))
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 409 and r.json()["detail"] == "no_checksums"
    assert helper.started == 0


def test_apply_refuses_when_there_is_nothing_newer(client, db_session, upd_dir, helper, inline):
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 409 and r.json()["detail"] == "no_update"
    app_settings.put(db_session, "update_check", stored_check("1.0.0"))
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 409 and r.json()["detail"] == "not_newer"
    app_settings.put(db_session, "update_check", stored_check("0.9.0"))
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 409 and r.json()["detail"] == "not_newer"


def test_apply_refuses_while_an_update_runs_and_without_a_helper(client, db_session, upd_dir, helper, inline, monkeypatch):
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    helper._available = False
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 503 and r.json()["detail"] == "helper_unavailable"
    helper._available = True
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    upd_dir.mkdir(parents=True, exist_ok=True)
    (upd_dir / "status.json").write_text(json.dumps({"id": "b" * 32, "phase": "backup", "updated_at": now}))
    r = client.post("/api/admin/updates/apply")
    assert r.status_code == 409 and r.json()["detail"] == "update_running"


def test_apply_reports_a_helper_that_would_not_start(client, db_session, upd_dir, helper, inline, monkeypatch):
    app_settings.put(db_session, "update_check", stored_check("1.1.0"))
    _wire(monkeypatch, _apply_files(sha(SETUP_FILE)))
    helper.fail = True
    client.post("/api/admin/updates/apply")
    run = client.get("/api/admin/updates/run").json()
    assert run["phase"] == "failed" and run["error_code"] == "helper_failed"
    assert not (upd_dir / "request.json").exists()


# ---------------------------------------------------------------------------
# Run state (what Admin polls)
# ---------------------------------------------------------------------------
def _status(upd_dir: Path, **fields):
    upd_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {"id": "c" * 32, "phase": "installing", "from_version": "1.0.0", "to_version": "1.1.0",
            "source": "github", "started_at": now, "updated_at": now}
    data.update(fields)
    (upd_dir / "status.json").write_text(json.dumps(data), encoding="utf-8")


def test_run_state_idle_active_and_final(upd_dir):
    assert updates.run_state()["phase"] == "idle"
    _status(upd_dir, phase="health_check")
    s = updates.run_state()
    assert s["phase"] == "health_check" and s["active"] is True and s["to_version"] == "1.1.0"
    _status(upd_dir, phase="rolled_back", error="The new version did not come up.")
    s = updates.run_state()
    assert s["phase"] == "rolled_back" and s["active"] is False and "did not come up" in s["error"]
    _status(upd_dir, phase="done")
    assert updates.run_state()["active"] is False


def test_run_state_marks_a_silent_updater_as_failed(upd_dir):
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _status(upd_dir, phase="queued", updated_at=old)
    s = updates.run_state()
    assert s["phase"] == "failed" and s["active"] is False and "start" in s["error"].lower()
    _status(upd_dir, phase="installing", updated_at=old)
    assert updates.run_state()["phase"] == "failed"


def test_run_state_survives_garbage_status_files(upd_dir):
    upd_dir.mkdir(parents=True)
    (upd_dir / "status.json").write_text("{ not json", encoding="utf-8")
    assert updates.run_state()["phase"] == "idle"
    (upd_dir / "status.json").write_text("\ufeff" + json.dumps({"id": "d" * 32, "phase": "done"}), encoding="utf-8")
    assert updates.run_state()["phase"] == "done"


# ---------------------------------------------------------------------------
# Phone app chain: the updated Setup's APK is what /api/client/android-app offers
# ---------------------------------------------------------------------------
def test_phone_app_offer_follows_the_apk_the_new_setup_installs(db_session, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.services.test_apk_stamp import _fake_signed_apk

    folder = tmp_path / "downloads"
    folder.mkdir()
    monkeypatch.setattr(settings, "f7five0_downloads_dir", str(folder))
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    user = User(username="phone-user", display_name="P", password_hash="x", role="member", is_active=True)
    db_session.add(user)
    db_session.commit()
    from app.api.deps import get_db

    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_user] = lambda: user
    try:
        c = TestClient(app)
        _fake_signed_apk(folder / "F7FIVE0-1.0.0.apk", [(0x7109871A, b"sig")])
        assert c.get("/api/client/android-app").json()["version"] == "1.0.0"
        # The new Setup copies its bundled APK in and drops the one it replaces.
        _fake_signed_apk(folder / "F7FIVE0-1.1.0.apk", [(0x7109871A, b"sig")])
        (folder / "F7FIVE0-1.0.0.apk").unlink()
        info = c.get("/api/client/android-app").json()
        assert info["available"] is True and info["version"] == "1.1.0"
        c.close()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def test_scheduler_checks_for_updates_daily_with_jitter():
    sched = scheduler.start()
    try:
        job = sched.get_job(scheduler.JOB_UPDATE_CHECK)
        assert job is not None
        assert job.trigger.interval == timedelta(days=1)
        assert job.trigger.jitter and job.trigger.jitter >= 60
        assert job.max_instances == 1
    finally:
        scheduler.shutdown()
