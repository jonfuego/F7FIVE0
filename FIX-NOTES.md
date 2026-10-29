# FIX-NOTES: fix/rerun-after-failed-install (hand test I-11)

## What was wrong

Setup decided "upgrade" from `.env` alone: `IsUpgrade` in `installer/F7FIVE0.iss`
was `FileExists(.env)` and `install.ps1` had `$IsUpgrade = Test-Path $EnvFile`.
`install.ps1` writes `.env` at step "Writing configuration (.env)", well before
"Creating admin account". A first install stopped after that point (the hand test
stopped it at "[11] Backend packages") left an `.env` and no users, so the rerun
skipped the Media, Admin, PostgreSQL, Access, Options and Ports pages, sent no
answers, and `install.ps1` skipped the admin account (`if (-not $IsUpgrade -and
$AdminUser)`) and the "Sign in as" line. Nobody could sign in.

Second problem found on the way: once the rerun is a new install again, its
"Database" step ran `ALTER ROLE f7five0 ... PASSWORD '<new random>'`, but
`Merge-EnvFile` never replaces an existing `DATABASE_URL`, so `.env` would keep
the first run's password and the API could not connect. Fixed in the same commit.

## The fix

- `common.ps1`: `Test-CompletedInstall $Root $ServiceRegistered`. Upgrade means
  `.env` exists AND either `data\install-complete.json` exists (new marker) or
  the `F7FIVE0-API` service is registered (installs made before the marker;
  every version registers the services only after the admin account step).
  `Write-InstallComplete` writes the marker (`{version, completed_at}`).
  `Get-DbUrlPassword` reads the f7five0 password out of a `DATABASE_URL`.
- `install.ps1`: `$IsUpgrade = Test-CompletedInstall $InstallDir (F7FIVE0-API
  service exists)`; the marker is written as the last thing in the `try` (after
  the summary), on new installs and upgrades alike, so old installs pick it up on
  their next upgrade (a failure to write it only warns: the service still counts);
  the Database step reuses the password already in `.env` (SQL-quoted) and
  generates one only when there is none.
- `F7FIVE0.iss`: `IsUpgrade` makes the same test (`.env` and
  (`data\install-complete.json` or `HKLM\SYSTEM\CurrentControlSet\Services\F7FIVE0-API`)).
  PrepareToInstall only stops services, so the answer is the same on the pages and
  at ssPostInstall.

Real upgrades: an Admin > Updates silent run (`/VERYSILENT`) and a wizard upgrade
always come from an install whose services are registered, so both stay upgrades,
including 1.0.x installs that have no marker. No new pages or settings.

## Files changed

- `installer/common.ps1`
- `installer/install.ps1`
- `installer/F7FIVE0.iss`
- `installer/tests/upgrade-detect.Tests.ps1` (new, 13 tests)
- `FIX-NOTES.md`

## Tests run (Windows PowerShell 5.1, this PC)

- `Invoke-Pester installer/tests/upgrade-detect.Tests.ps1` (Pester 3.4.0): 13 passed, 0 failed.
  Covers no `.env`, `.env` only (the I-11 case, now a new install), `.env` +
  marker, `.env` + service (pre-marker install), marker without `.env`,
  `Write-InstallComplete`, `Get-DbUrlPassword` (plain, quoted, percent-encoded,
  other user, no password), and source checks that install.ps1 and the .iss use
  the same marker path and service name.
- `Invoke-Pester installer/tests` (all): 87 passed, 0 failed (74 before + 13).
- `installer/tests/download-verify.ps1`, `update-verify.ps1`, `duckdns-migrate.ps1`: all checks passed.
- Parser `ParseFile` on every `installer/**/*.ps1`: 0 errors. Changed files are ASCII, CRLF.
- ISCC 6 compile of `F7FIVE0.iss` with a stub payload (in the scratch folder, not
  the repo): successful.
- Not run: the real installer (not allowed on this PC).

## For Jon to verify on the VM

1. I-11 again from the clean snapshot: Setup, stop Setup + install.ps1 after
   PostgreSQL is in, run Setup again. Expect: Media, Admin, Access, Options and
   Ports pages shown, no PostgreSQL password page, log shows "reusing the database
   password already in .env" and "Creating admin account", summary has "Sign in as",
   sign in works, `C:\F7FIVE0\data\install-complete.json` exists.
2. Wizard rerun of a finished install: pages skipped (upgrade), settings kept.
3. Upgrade a 1.0.18 install (no marker) with this Setup both by wizard and from
   Admin > Updates (silent): treated as upgrade, no admin page/account change,
   marker written at the end.
4. Optional edge: a pre-marker install that was uninstalled (services removed,
   `.env` and `data\` kept) and then reinstalled is now treated as a new install;
   it shows the wizard pages, keeps `.env` values and the database, and the admin
   step warns "already exists" for the same name. Installs that have the marker
   stay upgrades after an uninstall. Accepting this is a judgment call; say if you
   want it handled differently.
