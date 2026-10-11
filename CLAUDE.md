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
  off), `update.ps1` (the Admin > Updates updater, a SYSTEM task),
  `common.ps1` (helpers all of them dot-source), `uninstall.ps1`,
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
- Session-bound signed URLs (SEC-P1-2). Stream, HLS, art, subtitle, and
  download URLs are signed with the issuing session id (`sid`) and default to a
  4-hour TTL (`STREAM_URL_TTL_HOURS`). Each serve path verifies the HMAC first
  (no DB), then calls `app/services/signed_urls.py::session_authorizes`, which
  rejects a URL whose session is expired or explicitly revoked. The one subtlety
  is rotation: the web and native clients rotate their session on every ~15-min
  access-token refresh (old row gets `revoked_at` AND `rotated_at`). A session
  revoked *by rotation* still authorizes its already-issued URLs, so a 3-hour
  movie and a cast session keep playing across refreshes with no re-mint; only a
  real revoke (logout, password change, admin disable, reuse detection, all of
  which leave `rotated_at` null) or the 4-hour expiry kills a live URL. Starting
  new playback or a cast handoff calls `/api/stream/start` again and binds to
  the then-current session. When changing any signer, keep `sid` in both the
  HMAC payload and the query, and thread it through `_signed_query` so HLS
  sub-fetches stay bound.
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
- Trusted proxies (SEC-P1-1). Forwarded headers (`CF-Connecting-IP`,
  `X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`) are honoured
  only when the direct peer is a trusted proxy: loopback is always trusted,
  plus any IP/CIDR in `TRUSTED_PROXIES` (the front door runs on this host over
  loopback, so Setup writes loopback and the default is fine). The one helper
  is `app/services/trusted_proxy.py`: `real_client_ip` drives the audit log and
  the login throttle (a direct LAN caller can't spoof its IP), and
  `forwarded_origin` feeds `api/stream.py:_base_url`, which accepts a forwarded
  host only from a trusted peer AND only if it passes the allowlist (the
  configured public/home host, loopback, or a private LAN literal), else falls
  back to `PUBLIC_URL`, then loopback. So a hostile `X-Forwarded-Host` never
  lands in a signed URL. On the web side, `frontend/lib/origin.ts` is the
  matching helper: redirects (`proxy.ts`, `app/download/android/route.ts`) and
  the cookie `Secure` flag (`lib/cookies.ts`) build origins through it instead
  of trusting a raw browser `Host` / `X-Forwarded-Proto`. Session cookies are
  still `Secure` only over real HTTPS, so plain-HTTP LAN installs can sign in.
  The Next proxy hop is the one place a browser could forge a client-IP header
  that then reaches a trusted (loopback) backend peer, because Next 16's proxy
  cannot read the client socket peer IP. The launcher `server-wrapper.js` (which
  every production web launch runs instead of `server.js`) stamps the real socket
  peer as `x-f7five0-peer` (overwriting any client value) and sets the
  `F7FIVE0_LAUNCHER` process signal a client can never forge. `frontend/proxy.ts`
  trusts the peer only when that signal is present (fail closed without the
  launcher, so the backend records loopback). A loopback peer is a local front
  door (cloudflared / Caddy / Tailscale terminating on this host over loopback):
  its `CF-Connecting-IP` / `X-Forwarded-For` pass through. A LAN-browser peer has
  its forgeable client-IP headers (`CF-Connecting-IP`, `X-Forwarded-For`,
  `X-Real-IP`, `Forwarded`) stripped and `x-forwarded-for` set to the real peer
  IP. The `TRUSTED_PROXY_SECRET` / Caddy `header_up` `X-F7five0-Proxy` stays as an
  extra signal (a trusted hop keeps its genuine client-IP headers). Loopback-peer
  trust means any local process can set client-IP headers, which is the same
  trust the backend already gives a loopback peer. `x-forwarded-host` /
  `x-forwarded-proto` are always set from the allowlisted origin, never the raw
  header. The pure helper is `frontend/lib/forward-headers.ts`.
- Web process env: the Next proxy runs in the Node runtime and reads
  `PUBLIC_URL` / `HOME_URL` / `APP_ALLOWED_HOSTS` at runtime via
  `lib/origin.ts`, so those redirects and the CSRF self-origin only stay on the
  public host when the web process actually has them. The service env never
  carried them, so `server-wrapper.js` reads them from the install-root `.env`
  at start (install.ps1 passes `F7FIVE0_ENV_FILE`; a real service-env value
  still wins). `remote-access.ps1` writes a new `PUBLIC_URL` to the same `.env`
  then restarts `F7FIVE0-Web`, so the restart picks it up. `origin.ts` allows a
  LAN machine name on its own (a single label like `mediabox`, or a `.local`
  name); any other dotted name goes in `APP_ALLOWED_HOSTS`. A hostile dotted
  `Host` is still rejected and never lands in a `Location`.
- Libraries: when a `*_API_KEY` for Radarr/Sonarr/Lidarr is set, that app
  owns the library (`services/sync.py`). Otherwise `services/scan_library.py`
  scans `LIBRARY_ROOT_*` folders. Never let both write the same library.
  Requests need Radarr/Sonarr; `/api/client/features` tells clients (it also
  reports `arr: {radarr, sonarr, lidarr}`; Admin shows "Run *arr sync now"
  only when one is set up).
  The folder scan saves as it goes: it commits every 25 items (`BATCH_SIZE`)
  and at the end of each library, so rows show up while it runs and a library
  that fails loses only its open batch (the others still run). Never wrap a
  whole scan in one `db_session()`, which commits only on exit. Its state is
  the `app_settings` key `folder_scan_status` (`services/scan_status.py`:
  `state` idle/running, `current_library`, per-library `seen`, `added`,
  `probed`, `missing`, `errors`, `last_error`), written at the start, at every
  batch commit and at the end. API startup turns a stale `running` into `idle`
  with an "interrupted" note, and one folder scan runs at a time. Admin starts
  and reads it with `POST` / `GET /api/admin/library/scan` (409 while running);
  any signed-in user gets only `GET /api/library/scan-state` (`running`,
  `finished_at`), which the empty library pages use. Enrichment
  (`schedule_enrich_*`) is scheduled only after the commit that holds the row:
  the scan and `sync.py` collect ids and hand them over once committed. After
  each folder scan `scan_library.schedule_catch_up` queues movies, artists and
  albums that have a TMDB/MusicBrainz id but no `metadata_synced_at`, spaced a
  second apart.
  Per-file errors in the music scan are isolated: every MBID read from a tag
  goes through `scan_library.normalize_mbid` (split on whitespace, `/`, `;`, `,`,
  keep the first valid UUID), and each file imports inside a savepoint so one bad
  file rolls back only itself, is recorded with its path and a short reason (no
  raw SQL), counted, and the library ends "finished with N errors", never failed.
  The music-videos scan (`scan_music_videos.py`) writes its own status through
  `scan_status.py` (sibling key `music_videos_scan_status`) with a file total
  counted up front and a running count, and Admin shows it with the same progress
  bar as the folder scan.
- Artist aliases and merge: Admin can merge one artist into another
  (`services/artist_merge.py`). The source's name and MusicBrainz id are stored
  as an alias (table `artist_aliases`) that both `scan_library.py` and `sync.py`
  resolve through (`services/credits.py::resolve_artist`), so a rescan or *arr
  sync does not recreate the source. A merge record (`artist_merges`) backs an
  admin-only undo. `albums.credited_as` / `tracks.credited_as` keep the credited
  text. At scan time a "feat." / "ft." / "Featuring" credit attaches to the main
  artist; "&" and "And" are never auto-split.
- Fix Match and art search go beyond *arr: the admin lookup
  (`api/admin.py`) searches MusicBrainz (artist, album) and TMDB (movie, series
  via `tmdb_key.get()`) with *arr optional, and `services/art_search.py` uses
  `services/art_sources` (TMDB, AudioDB, iTunes) plus Cover Art Archive for
  albums. Each candidate carries a source tag; one source failing still returns
  the others. A TMDB series match gets a TMDB-backed refresh so applying it does
  something without Sonarr.
- Library folders: several per library (`app/services/library_folders.py`).
  Source is the `libraries` table once Admin > Library folders saves (then for
  every library), else `LIBRARY_ROOT_*` split on `;`. TV and music merge
  across folders; movies don't (same movie in two folders = two entries, the
  second copies details/art since `tmdb_id` is unique). An unreachable folder
  is skipped and its files keep their state; removing a folder in Admin marks
  its files missing.
- NAS sign-in: the services run as LocalSystem, which has no account on a NAS,
  so a UNC library share (`\\server\share`) can't be read until an admin enters
  a Windows sign-in for that server in Admin > Library folders.
  `app/services/nas_auth.py` is the one place this lives. Sign-ins are per
  server (`\\fuegonas` keyed as `fuegonas`, lowercased); one sign-in covers
  every share on that server. The password is encrypted with Windows DPAPI at
  machine scope (`CryptProtectData` with `CRYPTPROTECT_LOCAL_MACHINE`) and kept
  in `app_settings` under `nas_credentials`; it is never stored in `.env`,
  logged, returned to the browser, or written in plaintext. Shares are
  connected with `WNetAddConnection2W` using no local name, so no drive letter
  is ever mapped; a change cancels the existing connection first (avoids error
  1219). Windows scopes one set of credentials per server per logon session, so
  each process connects for itself: `nas_auth.ensure_all()` runs at API startup
  and stream-gateway startup, before every folder scan, in the Admin folder
  status check, and as a one-shot retry in the stream file-open path on a UNC
  error. Machine-scope DPAPI means any local process can decrypt the secret,
  the same trust boundary as `.env` and the DB password already on this host.
  Off Windows the endpoints answer 501 and `ensure_all()` is a no-op.
- TMDB key: always read it with `services/tmdb_key.get()` (Admin-saved key in
  `app_settings` wins over `TMDB_API_KEY`; cached per process, refreshed on
  save). Never read `settings.tmdb_api_key` directly. Admin reminder banners
  come from `services/reminders.py`.
- Logging: no secrets in logs. TMDB takes its key as `api_key=` in the URL and
  httpx logs request URLs at INFO, so `app/log_redact.py` `install()` runs right
  after `logging.basicConfig` in `main.py`, `stream.py` and every CLI command.
  It holds `httpx` and `httpcore` at WARNING and puts `RedactApiKeyFilter` on
  the root handler, which rewrites `api_key=<value>` to `api_key=***` in every
  record (message, arguments and traceback text). A new entry point must call
  `install()`; never log a URL or request that carries a key some other way.
- Scanner-imported art uses `source_kind` `local` or `tmdb`; admin-set art
  (`upload`, `url`, ...) is never overwritten.
- Art caching and size copies: every art save goes through
  `services/art.py::save_upload_bytes`, which also writes 300 px and 600 px
  WebP copies (`write_art_copies`). `GET /api/art/...` takes `w=300` or `w=600`
  (anything else serves the original), builds a missing copy on demand, and
  gives each size its own ETag. `Cache-Control` stays `private, max-age=31536000,
  immutable`; the `?v=<set_at>` key changes the URL when art changes. The web
  route (`app/api/art/[...path]/route.ts`) passes `Cache-Control`, `ETag` and
  `If-None-Match`/304 through, so never cap it with its own max-age. Grids and
  rails ask for `w=300` (`lib/art-url.ts`, `resolveArtUri` on the app). A one-time
  job (`backfill_art_copies`, run by the scheduler after boot) builds copies for
  older art and is safe to rerun. Art is private: Cloudflare must not cache it.
- Mix art: the four Home mixes (`recently-added`, `most-played`,
  `continue-listening`, `random`) are art kind `mix`, role `cover`, with a fixed
  uuid5 id per key. Admin sets or resets a picture from the mix cards; with no
  override the web shows the static default in `frontend/public/mix/`. Unknown
  mix keys are rejected.
- Frame-grab thumbs: when a music video has no thumb art, the music videos scan
  grabs one frame with ffmpeg (about 10 percent in) and saves it as
  `music_video` / `thumb` with `source_kind` `frame`. It runs in the scan, never
  in the stream worker. Any other art replaces a frame grab and is never
  replaced by one.
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
  `uv pip compile --universal --generate-hashes --python-version 3.12
  --output-file requirements.lock requirements.txt` (run uv from a throwaway
  venv or `uvx`/`pipx`, never add it to the runtime deps). The lock MUST be
  `--universal`: CI runs on Linux and Setup on Windows, so the lock has to
  carry platform-specific deps (for example `uvloop` on Linux, `colorama` on
  Windows) with their env markers, or `--require-hashes` fails on the other
  platform. Run pytest after. CI runs `pip-audit` against the lock through
  `scripts/pip_audit_gate.py`; any advisory it finds must be fixed or listed
  (with a reason and an expiry on or before 2027-01-06) in
  `backend/pip-audit-exceptions.txt`, or CI fails. Every `Image.open` in
  `backend/app` must pass an explicit `formats=` allowlist so Pillow never
  selects a parser outside JPEG/PNG/WEBP.
- Pinned installer downloads (SEC-P0-2): every file Setup fetches by a direct
  URL is pinned in `installer/downloads.manifest.psd1` to an exact version, an
  immutable URL (never a "latest" or rolling URL), and its SHA-256. Entries now:
  `node`, `ffmpeg` (used by `install.ps1`), and `cloudflared`, `caddy`,
  `tailscale` (used by `remote-access.ps1`). The scripts read specs with
  `Get-DownloadSpec` (in `common.ps1`) and pass Url + Sha256 (+ Publisher) to
  the `Download` helper, which REQUIRES a hash, verifies it with `Get-FileHash`,
  and on mismatch removes the file and throws. Signed binaries (cloudflared exe,
  Tailscale MSI) also carry `Publisher`; `Download` then requires a Valid
  `Get-AuthenticodeSignature` whose subject contains it. Caddy ships as a zip
  (GitHub has no bare Windows exe), so `remote-access.ps1` extracts `caddy.exe`
  after the hash check. Things installed by winget (Python, PostgreSQL, NSSM) or
  bundled (the APK) are NOT direct downloads and are NOT in the manifest. The
  offline logic test is `installer/tests/download-verify.ps1` (no network: it
  serves a fixture over `file://`); keep it green. `build-dist.ps1` copies the
  manifest into `dist/installer` so releases carry it.
  Refreshing a pinned download: (1) pick the exact new version and its immutable
  URL (a versioned path, not a "latest"/rolling one); for FFmpeg use gyan.dev's
  versioned `packages/ffmpeg-<ver>-essentials_build.zip`, for cloudflared the
  tagged `releases/download/<tag>/...` URL, for Caddy the tagged GitHub
  `caddy_<ver>_windows_amd64.zip`, for Tailscale the versioned
  `tailscale-setup-<ver>-amd64.msi`, for Node the `dist/v<ver>/...` zip.
  (2) Compute the hash from the real file:
  `(Get-FileHash -Algorithm SHA256 <downloaded-file>).Hash`. Prefer downloading
  the exact file; a vendor-published `.sha256`/SHASUMS is an acceptable source
  if it matches. (3) For a signed exe/msi confirm
  `(Get-AuthenticodeSignature <file>).Status` is `Valid` and copy the
  SignerCertificate Subject CN into `Publisher`. (4) Update Version, Url,
  Sha256, Publisher in `downloads.manifest.psd1`, then run
  `powershell -File installer\tests\download-verify.ps1` and parse-check the
  installer scripts.
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
- Updates: Admin > Updates updates the server from the latest GitHub release
  or an uploaded Setup (`backend/app/services/updates.py`,
  `installer/update.ps1`). Setup records the installed version in
  `<install>\version.json` (`install.ps1`, from the `appVersion` the Inno script
  passes); `services/server_version.py` reads it (fallback `0.0.0-dev`) and
  `/api/health` reports it. Once a day the scheduler (and "Check now") asks
  `api.github.com/repos/jonfuego/F7FIVE0/releases/latest` with no token, skips
  drafts and prereleases, and stores `{checked_at, latest, notes, setup_url,
  sums_url, error}` in `app_settings` `update_check`; a network error is stored,
  never raised. Admins get a badge on the Admin link when `latest` is newer.
  The stored answer can be a day old, so "Update now" asks GitHub again
  before it installs (`updates.begin_apply`), and falls back to the stored
  answer only when GitHub can't be reached. Updates are not cumulative: each
  release's Setup is a full installer, so a server can jump from any version to
  the latest.
  Nothing installs itself: the API verifies the Setup, writes
  `data/updates/request.json {id, setup_path, sha256, version, source}`, and
  starts the SYSTEM scheduled task `F7FIVE0-Update` (startable by the
  `-ServiceUser` account, like the Remote access task), which runs a copy of
  `update.ps1` kept in `data/updates/run` because Setup replaces the install
  folder mid-run. Two ways in, nothing else. (1) A release download: https only,
  hosts `github.com`, `objects.githubusercontent.com` and
  `release-assets.githubusercontent.com` (checked on every redirect), a size
  cap, and the Setup's SHA-256 must equal its line in the release's
  `SHA256SUMS.txt`; a release with no checksums is shown, never installed. (2) An
  uploaded Setup: the admin's own password again (header, checked before the file
  is read; five wrong tries lock it for 15 minutes), a PE exe under the cap, and
  either its SHA-256 equals the `F7FIVE0-Setup-<v>.exe` line of the published
  release for the version in the exe's own version info (not its name), or it
  has a Valid Authenticode signature whose signer subject equals
  `UPDATE_SIGNER_SUBJECT` (empty turns that off; until releases are signed only
  the first applies, and unsigned test builds are refused by design). Never the
  same or an older version (a prerelease sorts below its release): the API and
  the updater both refuse. The updater copies the Setup into `run\` (Admins and
  SYSTEM only) and checks and runs that copy; stops the services and `pg_dump -Fc`
  to `data/updates/backup/<from>-<id>.dump` (a new version can migrate the
  schema, so code alone is not enough to go back); runs Setup with
  `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`; waits up to 5 minutes for
  `/api/health` to report the new version and `/stream/health` and the web port
  to answer 200; on any failure `pg_restore --clean`, runs the cached previous
  Setup (`data/updates/setup`, copied there by Setup itself via `{srcexe}`, kept
  to the current and previous version; the `.iss` skips that copy when Setup runs
  from the cache, which is how a rollback runs), and health-checks the old
  version. It refuses to start without that cached Setup. `status.json` carries
  the phases `verifying`, `backup`, `installing`, `health_check`, then `done`,
  `rolled_back` or `failed` (plus `queued`, `downloading`, `rolling_back`); the
  page polls it across the restart. A silent upgrade keeps settings: the wizard
  sends answers only on a new install, `.env` keys that exist always win
  (`Merge-EnvFile`), and an upgrade keeps the Windows account the services
  already run as. Phones: every Setup bundles the matching APK, so updating the
  server is updating the app; `GET /api/client/android-app` then reports the new
  version and the app's own "Update from your server" offer follows.
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
`[System.Management.Automation.Language.Parser]::ParseFile(...)`, run
`installer\tests\download-verify.ps1` and `installer\tests\update-verify.ps1`
under Windows PowerShell 5.1 (`powershell.exe`, not `pwsh`), and do a real run
on a clean Windows VM before tagging a release. Self-update (Admin > Updates)
is only proven by a real update on a VM: the tests use a stub Setup.
