#!/usr/bin/env python3
"""CI gate: audit the hashed backend lock and fail on any advisory that is not
listed (and unexpired) in backend/pip-audit-exceptions.txt.

Runs pip-audit against backend/requirements.lock (the fully pinned, hashed
resolution the build and installer consume) and compares the findings to the
reviewed exception list. Exits non-zero on any finding that is not excepted,
or whose exception has expired.

pip-audit is expected on PATH (CI installs it in an isolated step, e.g.
`pipx install pip-audit`); it is never added to the backend's runtime deps.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "backend" / "requirements.lock"
EXC = ROOT / "backend" / "pip-audit-exceptions.txt"
# Spec cap: no exception may be dated later than this.
HARD_EXPIRY = dt.date(2027, 1, 6)


def load_exceptions() -> dict[str, dt.date]:
    """Parse the exceptions file into {ADVISORY_ID: expiry_date}."""
    exc: dict[str, dt.date] = {}
    if not EXC.exists():
        return exc
    for raw in EXC.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            sys.exit(
                "pip-audit-exceptions.txt: expected 'ID | reason | "
                f"YYYY-MM-DD', got: {raw!r}"
            )
        advid, _reason, expiry = parts
        try:
            when = dt.date.fromisoformat(expiry)
        except ValueError:
            sys.exit(f"pip-audit-exceptions.txt: bad date for {advid}: {expiry!r}")
        if when > HARD_EXPIRY:
            sys.exit(
                f"pip-audit-exceptions.txt: {advid} expiry {expiry} is after "
                f"the hard cap {HARD_EXPIRY.isoformat()}"
            )
        exc[advid.upper()] = when
    return exc


def audit_cmd() -> list[str]:
    exe = shutil.which("pip-audit")
    if exe:
        return [exe]
    return [sys.executable, "-m", "pip_audit"]


def main() -> None:
    if not LOCK.exists():
        sys.exit(f"lock not found: {LOCK}")
    proc = subprocess.run(
        [*audit_cmd(), "--no-deps", "-r", str(LOCK), "--format", "json"],
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout + "\n" + proc.stderr + "\n")
        sys.exit("pip-audit produced no JSON (see output above)")

    exceptions = load_exceptions()
    today = dt.date.today()
    problems: list[str] = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            vid = str(vuln.get("id", "")).upper()
            ids = {vid} | {str(a).upper() for a in vuln.get("aliases", [])}
            matched = ids & set(exceptions)
            if not matched:
                problems.append(f"{dep['name']} {dep['version']}: {vid} (not excepted)")
                continue
            for m in matched:
                if exceptions[m] < today:
                    problems.append(
                        f"{dep['name']} {dep['version']}: {vid} "
                        f"(exception {m} EXPIRED {exceptions[m].isoformat()})"
                    )

    if problems:
        print("pip-audit gate FAILED:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    print("pip-audit gate OK: no findings outside the unexpired exception list.")


if __name__ == "__main__":
    main()
