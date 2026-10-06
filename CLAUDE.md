# F7FIVE0: notes for AI coding sessions

Self-hosted media server (movies, TV, music, music videos) for Windows.
Public domain (Unlicense). Read README.md for the product view and
INSTALL.md for the operator view.

## Layout

- `backend/`: FastAPI. Two apps, one codebase: `app.main:app` (API, :8001)
  and `app.stream:app` (stream gateway, :8002). Do not merge them.
- `frontend/`: Next.js 16 App Router, strict TypeScript, Tailwind. Built as
  a standalone bundle; runs as `node server.js` on :3001.
- `mobile/`: Expo SDK 54 + react-native-tvos 0.81, old architecture
  (phone, Android TV, Android Auto). `npm ci` relies on `.npmrc` legacy-peer-deps.
- `installer/`: `install.ps1` (does all the work, idempotent),
  `remote-access.ps1` (Tailscale / Cloudflare / port forwarding / token /
  off), `common.ps1` (helpers both dot-source), `uninstall.ps1`,
  `build-dist.ps1` (assembles the release payload; list new installer files
  there), `F7FIVE0.iss` (Inno Setup wizard that only collects answers).
- `scripts/`: dev helpers, `publish.ps1` (deploy a git checkout to
  C:\F7FIVE0), nightly backup.
- `.github/workflows/`: CI (pytest, web build, mobile tsc+jest) and Release
  (tag `v*` -> Setup.exe + zip on a GitHub release).

## Rules that matter

- Windows host. PowerShell 5.1 compatible scripts, ASCII only (5.1 misreads
  UTF-8 without BOM). Under `$ErrorActionPreference = "Stop"`, never
  redirect native stderr (`2>`); flip to Continue and check `$LASTEXITCODE`.
- Install folder ACL (`Set-InstallAcl` in `common.ps1`, run first by
  `install.ps1`): owner Administrators, no inheritance, Administrators and
  SYSTEM full, Users read/execute; `data\` and `logs\` drop Users and give
  the `-ServiceUser` account modify; `.env` is Administrators/SYSTEM plus read
  for the service account. Services run code from here, so never loosen it,
  and any rewrite of `.env` re-applies `Set-PrivateAcl $EnvFile` with the
  service account SID. Exception for Setup's own logs: the `logs\` folder gives
  Users read/list on the folder node only (no inheritance), and `install.ps1`
  grants Users read on `install-*.log` and `setup-summary.txt` so a non-elevated
  user can read them; service logs (`F7FIVE0-*.out/err.log`) stay private because
  the folder grant does not inherit to files.
- The stream gateway runs one uvicorn worker (in-process transcoder
  registry). It validates the HMAC signature before any DB lookup.
- Stream roots fail closed (SEC-P0-4). The gateway derives its allowed roots
  from the active library-folder configuration (the `libraries` table, else
  `LIBRARY_ROOT_*`) plus any `STREAM_ALLOWED_ROOTS`, and rejects any media
  path not under one of them (`ensure_under_roots`, case- and UNC-aware). With
  no roots configured it serves nothing; there is no "empty means allow
  everything" path. The only bypass is `STREAM_UNSAFE_ALLOW_ANY_PATH` (off by
  default, never written by Setup, for local dev only). Setup does not need to
  write `STREAM_ALLOWED_ROOTS`; the library folders supply the roots.
- HLS playlists are rewritten so every URI carries the signed query.
- Tokens never reach the browser. Browser calls go through the Next BFF
  routes (`/api/session|library|stream|admin|art|requests/*`).
- Single origin: `frontend/proxy.ts` (formerly middleware) proxies `/stream/*` to the stream
  gateway, non-BFF `/api/*` to the API, and BFF paths to the API when the
  request carries a Bearer token or a signed `sig` query (native app).
  Users expose one port (3001) or one tunnel hostname.
- Backend builds absolute URLs from `X-Forwarded-Host` / `X-Forwarded-Proto`
  (see `api/stream.py:_base_url`). Session cookies are `Secure` only when
  the request arrived over HTTPS (`lib/cookies.ts`), so plain-HTTP LAN
  installs can sign in.
- Libraries: when a `*_API_KEY` for Radarr/Sonarr/Lidarr is set, that app
  owns the library (`services/sync.py`). Otherwise `services/scan_library.py`
  scans `LIBRARY_ROOT_*` folders. Never let both write the same library.
  Requests need Radarr/Sonarr; `/api/client/features` tells clients.
- Library folders: several per library (`app/services/library_folders.py`).
  Source is the `libraries` table once Admin > Library folders saves (then for
  every library), else `LIBRARY_ROOT_*` split on `;`. TV and music merge
  across folders; movies don't (same movie in two folders = two entries, the
  second copies details/art since `tmdb_id` is unique). An unreachable folder
  is skipped and its files keep their state; removing a folder in Admin marks
  its files missing.
- TMDB key: always read it with `services/tmdb_key.get()` (Admin-saved key in
  `app_settings` wins over `TMDB_API_KEY`; cached per process, refreshed on
  save). Never read `settings.tmdb_api_key` directly. Admin reminder banners
  come from `services/reminders.py`.
- Scanner-imported art uses `source_kind` `local` or `tmdb`; admin-set art
  (`upload`, `url`, ...) is never overwritten.
- Migrations go through Alembic. Keep revision ids stable: existing installs
  upgrade through them. Register new models in `app/models/__init__.py`.
- Config comes from `.env` at the install root via pydantic-settings. New
  settings need a default, an `.env.example` entry, and (if setup should
  write it) a line in `install.ps1`.
- Backend dependency lock (SEC-P0-1): `backend/requirements.txt` holds loose
  direct ranges; `backend/requirements.lock` is the exact, hash-pinned
  resolution CI and the installer consume with `pip install --require-hashes`.
  Never install the backend from `requirements.txt` in CI or Setup. To bump a
  dependency: edit `requirements.txt`, then regenerate the lock with
  `pip-compile --generate-hashes --output-file requirements.lock
  requirements.txt` (run pip-tools from a throwaway venv or `pipx`/`uvx`, never
  add it to the runtime deps), targeting Python 3.12 (the CI/Setup runtime),
  then run pytest. CI runs `pip-audit` against the lock through
  `scripts/pip_audit_gate.py`; any advisory it finds must be fixed or listed
  (with a reason and an expiry on or before 2027-01-06) in
  `backend/pip-audit-exceptions.txt`, or CI fails. Every `Image.open` in
  `backend/app` must pass an explicit `formats=` allowlist so Pillow never
  selects a parser outside JPEG/PNG/WEBP.
- Setup installs for home use only and never waits on a person. Remote access
  is set up afterwards from Admin > Remote access: the API writes
  `data/remote-access/request.json` and starts the `F7FIVE0-RemoteAccess`
  scheduled task (SYSTEM, on demand, startable by the service account), which
  runs `installer/remote-access.ps1 -FromRequest` and reports through
  `status.json` / `run.log` (`backend/app/services/remote_access.py` is the
  other side). The helper treats the request as untrusted input. Methods:
  Tailscale Funnel; a named Cloudflare tunnel run by its own NSSM service
  `F7FIVE0-Tunnel` (never touch a pre-existing `Cloudflared` service); a
  dashboard tunnel token (same service); or Caddy (`F7FIVE0-Proxy`, automatic
  HTTPS, optional DuckDNS refresh task). Never offer plain-HTTP port
  forwarding. The result lands in `.env` as `PUBLIC_URL`; the helper restarts
  API and Web, and clients read it from `/api/client/features`.
  `install.ps1 -RemoteAccess <method>` and `remote-access.ps1 -Method` are the
  console (advanced / recovery) paths.
- Passkeys (WebAuthn) are on only when an RP id resolves (WEBAUTHN_RP_ID or
  the host of an https PUBLIC_URL); clients read `/api/client/features`.
  Allowed Android apps and certs come from WEBAUTHN_ANDROID_CERT_SHA256 /
  WEBAUTHN_EXTRA_ANDROID_APPS (blank = the official cert,
  `OFFICIAL_ANDROID_CERT_SHA256` in `config.py`). `/.well-known/assetlinks.json`
  is generated by the API and proxied by `proxy.ts`; never ship a static one.
- Official APKs are signed locally with `scripts\release-apk.ps1`. No signing
  keys or secrets in CI. Phone builds are 64-bit (`arm64-v8a`); a 32-bit
  `-armv7` build is optional. The script uploads to a draft release; pushing
  the tag makes CI bundle the APK into Setup.exe (no APK, no release), and
  `install.ps1` copies it into `data/downloads`, so the server and the app it
  hands out are always the same version.
- Android downloads are stamped, never re-signed: the API adds the server's
  addresses (PUBLIC_URL, the address used, HOME_URL or LAN IP) as one pair in
  the APK Signing Block (`services/apk_stamp.py`, `services/android_app.py`,
  `/api/client/android-app*`); the app reads it back with
  `mobile/modules/f7five0-stamp`. Pair id 0x46374635 is fixed: installed apps
  look for it. `/download/android` (web) only redirects to a signed link.
- Saved library views (which Music browse tab, movie genre and sort, TV
  filter, Music Videos order, Mixes picker values; on the app the hub chips,
  sort/filter and genre) live on the server, per user, in `user_view_prefs`:
  `GET /api/view-prefs` and `PUT /api/view-prefs/{key}` (web through the
  library BFF at `/api/library/view-prefs`). Web pages use `useViewPref` from
  `frontend/lib/use-view-pref.ts` (keys, defaults and allowed values in
  `lib/view-prefs.ts`); the app uses `useViewPref` from
  `mobile/src/state/viewPrefs.ts`. Don't keep view state only in
  localStorage or AsyncStorage; the app's AsyncStorage copy is a cache.
- Admin-only account creation. No self-serve sign-up.
- Writing style for docs, comments, and commits: plain and direct, no em
  dashes.

## Design system

`design/` is an export of the F7FIVE0 Design System artifact in Claude, not
hand-maintained source. The web and app read from copies of it:

- `frontend/app/f7five0-tokens.css` is a byte-identical copy of
  `design/f7five0_tokens_v3.css`, imported by `app/globals.css`.
- `frontend/tailwind.preset.ts` is a byte-identical copy of
  `design/f7five0_tailwind-preset_v3.ts`, used by `tailwind.config.ts`.
- `mobile/src/state/f7five0-theme.ts` is a byte-identical copy of
  `design/f7five0_rn-theme_v3.ts`; `mobile/src/state/theme.ts` builds on it.

Keep those three copies byte-identical to `design/`. To change tokens, edit the
artifact, re-export into `design/`, and re-copy. Fonts are Archivo (400 to 900);
icons are Lucide (stroke 2.25, square caps, miter joins) behind the shared
`Icon` components. Marks come from `design/logos/`; the web and mobile asset
scripts render from there. Dark only this pass; the light token block is unused.

## Checks before calling something done

```powershell
cd backend; python -m pytest -q
cd frontend; npm run build; npm run lint
cd mobile; npm run typecheck; npm test
```

Installer changes: parse-check with
`[System.Management.Automation.Language.Parser]::ParseFile(...)` and do a
real run on a clean Windows VM before tagging a release.
