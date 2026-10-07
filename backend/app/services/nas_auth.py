r"""NAS sign-in: let an admin store a Windows sign-in for a network share and
connect the share so the F7FIVE0 services (which run as LocalSystem by
default) can read it.

Why this exists
---------------
The services run as LocalSystem, which has no account on the NAS, so a UNC
library folder like ``\\fuegonas\The Hive\Movies`` shows up as "can't open"
even though the share is fine. Rather than run the services as a Windows user,
the admin enters the NAS sign-in here. We store the password encrypted with
Windows DPAPI at machine scope and connect the share with
``WNetAddConnection2W`` (no drive letter, so nothing is mapped into any user's
profile). Each process that needs the share calls :func:`ensure_all` itself,
because Windows scopes one set of credentials per server per logon session and
a ``-ServiceUser`` process gets its own session.

Design notes
------------
- Credentials are keyed per server (``\\fuegonas`` -> ``fuegonas``, lowercased).
  One sign-in covers every share and folder on that server.
- Stored in ``app_settings`` under ``nas_credentials`` as
  ``{server: {username, secret, updated_at}}``. ``secret`` is base64 of the
  DPAPI blob. The plaintext password is never stored, logged, or returned.
- The DPAPI layer (:func:`_protect` / :func:`_unprotect`) and the WNet layer
  (:func:`_wnet_add` / :func:`_wnet_cancel`) are tiny functions so tests can
  stub them and CI on Linux never touches a real Windows API.
- Off Windows the endpoints answer 501 and :func:`ensure_all` is a no-op.

Trust boundary
--------------
Machine-scope DPAPI (``CRYPTPROTECT_LOCAL_MACHINE``) means any process on this
PC can decrypt the secret. That is the same boundary as ``.env`` and the DB
password already living on this host, so it is not a downgrade.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("f7five0.nas_auth")

SETTING_KEY = "nas_credentials"

# Fixed secondary entropy mixed into every DPAPI blob. Not a secret (it ships
# in the source); it just scopes the ciphertext to this feature.
_ENTROPY = b"F7FIVE0/nas-sign-in/v1"

# Win32 flags.
CRYPTPROTECT_LOCAL_MACHINE = 0x4
RESOURCETYPE_DISK = 0x1

# Windows error codes -> a short reason the UI can turn into plain text. Codes
# not listed fall through to "error" and keep their number (see reason_text).
_CODE_REASON: dict[int, str] = {
    0: "ok",
    86: "bad_credentials",      # ERROR_INVALID_PASSWORD
    1326: "bad_credentials",    # ERROR_LOGON_FAILURE
    53: "unreachable",          # ERROR_BAD_NETPATH
    1231: "unreachable",        # ERROR_NETWORK_UNREACHABLE
    67: "share_not_found",      # ERROR_BAD_NET_NAME
    5: "access_denied",         # ERROR_ACCESS_DENIED
    1219: "credential_conflict",  # ERROR_SESSION_CREDENTIAL_CONFLICT
    # 1327..1331 and 1909 are all "this account can't log in right now".
    1327: "account_blocked",    # ERROR_ACCOUNT_RESTRICTION
    1328: "account_blocked",    # ERROR_INVALID_LOGON_HOURS
    1329: "account_blocked",    # ERROR_INVALID_WORKSTATION
    1330: "account_blocked",    # ERROR_PASSWORD_EXPIRED
    1331: "account_blocked",    # ERROR_ACCOUNT_DISABLED
    1909: "account_blocked",    # ERROR_ACCOUNT_LOCKED_OUT
}

_REASON_TEXT: dict[str, str] = {
    "ok": "connected",
    "bad_credentials": "wrong username or password",
    "unreachable": "can't reach the NAS",
    "share_not_found": "share not found",
    "access_denied": "this account can't open the folder",
    "credential_conflict": "Windows already has a different sign-in for this NAS",
    "account_blocked": "account locked or disabled",
}


# ---------------------------------------------------------------------------
# Platform guards
# ---------------------------------------------------------------------------
def is_windows() -> bool:
    return os.name == "nt"


def available() -> bool:
    """Whether DPAPI + WNet can run here. Off Windows the endpoints answer 501
    and ensure_all() is a no-op."""
    return is_windows()


# ---------------------------------------------------------------------------
# UNC parsing
# ---------------------------------------------------------------------------
def is_unc_path(path: str) -> bool:
    p = (path or "").replace("/", "\\")
    return p.startswith("\\\\") and len(p) > 2


def split_unc(path: str) -> tuple[str, str]:
    r"""``\\server\share\sub\dir`` -> ``("server", "share")``. The server is
    lowercased (it is the per-server key). Raises ValueError if not a UNC path
    with at least a server and a share."""
    if not is_unc_path(path):
        raise ValueError(f"not a UNC path: {path!r}")
    parts = [p for p in path.replace("/", "\\")[2:].split("\\") if p]
    if len(parts) < 2:
        raise ValueError(f"UNC path has no share: {path!r}")
    return parts[0].lower(), parts[1]


def server_of(path: str) -> str:
    return split_unc(path)[0]


def remote_name(path: str) -> str:
    r"""The ``\\server\share`` to hand WNet (the first two UNC parts)."""
    server, share = split_unc(path)
    return f"\\\\{server}\\{share}"


# ---------------------------------------------------------------------------
# DPAPI layer (stubbed in tests)
# ---------------------------------------------------------------------------
def _protect(plaintext: str) -> bytes:
    """Encrypt with CryptProtectData at machine scope + fixed entropy."""
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _mk(data: bytes) -> _BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    data_in = _mk(plaintext.encode("utf-8"))
    entropy = _mk(_ENTROPY)
    out = _BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy),
        None, None, CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _unprotect(blob: bytes) -> str:
    """Decrypt a CryptProtectData blob made by :func:`_protect`."""
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _mk(data: bytes) -> _BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    data_in = _mk(blob)
    entropy = _mk(_ENTROPY)
    out = _BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy),
        None, None, CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---------------------------------------------------------------------------
# WNet layer (stubbed in tests)
# ---------------------------------------------------------------------------
def _wnet_add(remote: str, username: str, password: str) -> int:
    r"""WNetAddConnection2W for ``\\server\share`` with no local name (no drive
    letter is ever mapped). Returns the Win32 error code (0 == connected)."""
    import ctypes
    from ctypes import wintypes

    class _NETRESOURCE(ctypes.Structure):
        _fields_ = [
            ("dwScope", wintypes.DWORD),
            ("dwType", wintypes.DWORD),
            ("dwDisplayType", wintypes.DWORD),
            ("dwUsage", wintypes.DWORD),
            ("lpLocalName", wintypes.LPWSTR),
            ("lpRemoteName", wintypes.LPWSTR),
            ("lpComment", wintypes.LPWSTR),
            ("lpProvider", wintypes.LPWSTR),
        ]

    nr = _NETRESOURCE()
    nr.dwType = RESOURCETYPE_DISK
    nr.lpLocalName = None       # NULL: connect the share, map no drive letter
    nr.lpRemoteName = remote
    nr.lpProvider = None
    return int(ctypes.windll.mpr.WNetAddConnection2W(
        ctypes.byref(nr), password, username, 0,
    ))


def _wnet_cancel(remote: str) -> int:
    r"""WNetCancelConnection2W for ``\\server\share`` (force = True). Returns
    the Win32 error code; callers ignore it (nothing to cancel is fine)."""
    import ctypes
    return int(ctypes.windll.mpr.WNetCancelConnection2W(remote, 0, True))


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------
def reason_for_code(code: int) -> str:
    return _CODE_REASON.get(int(code), "error")


def reason_text(reason: str, code: Optional[int] = None) -> str:
    """Plain English for a reason. The generic "error" keeps its number."""
    if reason == "error":
        return f"Windows error {code}" if code is not None else "an unexpected error"
    return _REASON_TEXT.get(reason, reason)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _load(db) -> dict:
    from app.services import app_settings
    return dict(app_settings.get(db, SETTING_KEY) or {})


def _store(db, record: dict) -> None:
    from app.services import app_settings
    if record:
        app_settings.put(db, SETTING_KEY, record)
    else:
        app_settings.delete(db, SETTING_KEY)


def list_servers(db) -> list[dict]:
    """GET shape: one row per server, username and updated_at only. No secret."""
    record = _load(db)
    return [
        {"server": server, "username": v.get("username", ""), "updated_at": v.get("updated_at")}
        for server, v in sorted(record.items())
    ]


def username_for(db, path: str) -> Optional[str]:
    """The saved username for the server this UNC path lives on, or None."""
    if not is_unc_path(path):
        return None
    try:
        server = server_of(path)
    except ValueError:
        return None
    rec = _load(db).get(server)
    return rec.get("username") if rec else None


def _password_for(db, server: str) -> Optional[str]:
    rec = _load(db).get(server)
    if not rec:
        return None
    try:
        return _unprotect(base64.b64decode(rec["secret"]))
    except Exception:
        log.warning("could not decrypt the stored NAS secret for %s", server, exc_info=True)
        return None


def _server_shares(db, server: str) -> list[str]:
    r"""Distinct ``\\server\share`` remote names among the library folders that
    live on `server`. One sign-in covers every share, so a change reconnects
    all of them."""
    from app.services import library_folders
    out: list[str] = []
    seen: set[str] = set()
    for paths in library_folders.all_folders(db).values():
        for p in paths:
            if not is_unc_path(p):
                continue
            try:
                if server_of(p) != server:
                    continue
                remote = remote_name(p)
            except ValueError:
                continue
            key = remote.lower()
            if key not in seen:
                seen.add(key)
                out.append(remote)
    return out


# ---------------------------------------------------------------------------
# Save / remove / connect
# ---------------------------------------------------------------------------
def save(db, server: str, username: str, password: str) -> dict:
    """Store the sign-in for `server` (encrypted), then reconnect every known
    share on it: cancel first (so a changed password does not hit error 1219),
    then connect. Returns the per-share connect status. Never returns the
    password or the stored secret."""
    server = server.strip().lstrip("\\").lower()
    username = username.strip()
    record = _load(db)
    secret = base64.b64encode(_protect(password)).decode("ascii")
    updated_at = datetime.now(timezone.utc).isoformat()
    record[server] = {"username": username, "secret": secret, "updated_at": updated_at}
    _store(db, record)

    shares: list[dict] = []
    for remote in _server_shares(db, server):
        _wnet_cancel(remote)            # drop any stale connection first
        code = _wnet_add(remote, username, password)
        shares.append({"share": remote, "reason": reason_for_code(code), "code": int(code)})
    return {"server": server, "username": username, "updated_at": updated_at, "shares": shares}


def remove(db, server: str) -> None:
    """Forget the sign-in for `server` and cancel its share connections."""
    server = server.strip().lstrip("\\").lower()
    for remote in _server_shares(db, server):
        _wnet_cancel(remote)
    record = _load(db)
    if server in record:
        del record[server]
        _store(db, record)


def ensure_all(db=None) -> None:
    """Connect every UNC library folder whose server has a saved sign-in.
    Cheap when already connected (WNetAddConnection2 on a live connection just
    returns). A no-op off Windows or when nothing is saved. Opens its own DB
    session when `db` is None."""
    if not available():
        return
    if db is None:
        from app.db import db_session
        try:
            with db_session() as own:
                ensure_all(own)
        except Exception:
            log.warning("ensure_all could not open a session", exc_info=True)
        return

    from app.services import library_folders
    record = _load(db)
    if not record:
        return
    for paths in library_folders.all_folders(db).values():
        for p in paths:
            if not is_unc_path(p):
                continue
            try:
                server = server_of(p)
            except ValueError:
                continue
            rec = record.get(server)
            if not rec:
                continue
            password = _password_for(db, server)
            if password is None:
                continue
            try:
                _wnet_add(remote_name(p), rec.get("username", ""), password)
            except Exception:
                log.warning("ensure_all could not connect %s", p, exc_info=True)
