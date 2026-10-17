# F7FIVE0: notes for AI coding sessions

Self-hosted media server (movies, TV, music, music videos, podcasts) for Windows.
Public domain (Unlicense). Read README.md for the product view and
INSTALL.md for the operator view.

## Layout

- `backend/`: FastAPI. Two apps, one codebase: `app.main:app` (API, :8001)
  and `app.stream:app` (stream gateway, :8002). Do not merge them. Podcasts
  (feeds, search, downloads, relay, local scan) are `services/podcasts/` and
  `api/podcasts.py`; the web and phone apps both have a Podcasts section.
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
  On an upgrade (the root is already owned by Administrators) `Set-InstallAcl
  -Upgrade` sets the owner on `data\` and `logs\` themselves only, not on every
  file inside: the art copies and transcode cache can make that walk slow.
  Every install step prints its clock time and how long it took.
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
  sub-fetches stay bound. The 120 s access-token grace in
  `api/deps.py::current_user` follows the same rule: it applies only to a session
  revoked by rotation (`rotated_at` set). Logout, logout-all, password change,
  admin revoke or disable and refresh-reuse detection reject the next request at
  once, and each of them evicts the revoked sessions from the session cache after
  its commit (`evict_session_caches`). The cache entry carries `rotated_at`.
- Stream roots fail closed (SEC-P0-4). The gateway derives its allowed roots
  from the active library-folder configuration (the `libraries` table, else
  `LIBRARY_ROOT_*`) plus any `STREAM_ALLOWED_ROOTS`, and rejects any media
  path not under one of them (`ensure_under_roots`, case- and UNC-aware). With
  no roots configured it serves nothing; there is no "empty means allow
  everything" path. The only bypass is `STREAM_UNSAFE_ALLOW_ANY_PATH` (off by
  default, never written by Setup, for local dev only). Setup does not need to
  write `STREAM_ALLOWED_ROOTS`; the library folders supply the roots. The gateway
  is not the only reader of media paths: every other read, probe, extract or byte
  response (API download, streams, subtitles, stream start, lyrics and its `.lrc`
  sidecar, audio and marker analysis, podcast chapters) goes through the one
  helper `app/services/media_paths.py` (`resolve_contained_media_path`, which
  translates the stored path with `path_map` and applies the same roots, and
  `is_contained`; `stream.py` uses the same `allowed_roots` and `contain`). Never
  call `path_map.translate(mf.path)` and read the result. An outside path answers
  403 `path_outside_library_roots`. The *arr sync checks a path reported by
  Radarr, Sonarr or Lidarr before the first probe, never probes or stores a path
  outside the roots, and counts it in `SyncStats.files_refused`.
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
- Libraries: when a Radarr/Sonarr/Lidarr API key is set, that app owns the
  library (`services/sync.py`). Otherwise `services/scan_library.py`
  scans `LIBRARY_ROOT_*` folders. Never let both write the same library.
  Requests need Radarr/Sonarr; `/api/client/features` tells clients (it also
  reports `arr: {radarr, sonarr, lidarr}`).
- *arr settings (Admin > *arr card): never read `settings.radarr_*`,
  `settings.sonarr_*`, `settings.lidarr_*` or `settings.arr_webhook_secret`
  directly. Use `services/arr_settings` (`creds(app)`, `url(app)`,
  `api_key(app)`, `configured(app)`, `quality_profile_id(app)`,
  `root_folder(app)`, `webhook_secret()`). A value saved in Admin
  (`app_settings` keys `arr:<app>` and `arr_webhook_secret`) wins over `.env`
  per field, a blank saved value means use `.env`, and the cache is replaced on
  save, so no restart is needed. The admin endpoints (`api/admin_arr.py`, under
  `/api/admin/arr`) never return a stored key, only `has_key` and a masked tail.
  The card says that a key hands that library from the folder scan to the app.
  The webhook receiver takes the token as the `X-Arr-Webhook-Token` header or
  the Basic-auth password, never in the query string. Setup generates
  `ARR_WEBHOOK_SECRET` when it is blank (`install.ps1`, upgrades included; a
  non-blank value never changes).
- Admin > Scans is the one place to start and watch scans: Movies, TV, Music,
  Music videos, Podcasts (the folder scan of the podcasts library), Podcast feeds
  (Refresh feeds; not part of Scan all) and the *arr sync, with Scan all and a
  button per row. The rows
  come from the pure helper `frontend/lib/scans-rows.ts`. Music is driven by the
  folder scan when Lidarr is not set and by the Lidarr sync when it is, so music
  is always scannable. `POST /api/admin/library/scan?library=movies|tv|music`
  (repeatable) starts one folder library and answers 400 `library_not_scanned`
  for a library an *arr app owns; `POST /api/sync/run?app=<app>` syncs one app,
  and the *arr sync keeps its own status (`arr_sync_status`,
  `GET /api/admin/library/arr-sync`). Library folders keeps folder editing and
  NAS sign-in only.
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
  Merge also moves the source's music video releases and videos (they cascade
  with their artist, so a merge used to delete them); undo moves them back, with
  the release ids kept in `source_snapshot._moved_music_video_release_ids` (no
  migration). A release folder both artists have stops the merge (422) with
  nothing changed. The music videos scan (`scan_music_videos._upsert_artist`)
  files an artist folder under a merge alias, then the same name, then the one
  artist with the same `art_sources/names.py::match_key` folding ("Birthday
  Party" under "The Birthday Party"); two or more candidates make a new artist.
  Fix Match checks `_check_mbid_free` first: a MusicBrainz id another artist
  already holds answers 409 `already_matched` naming the holder, and the fix is
  Merge into... (also on the Music Videos artist page).
- Fix Match and art search go beyond *arr: the admin lookup
  (`api/admin.py`) searches MusicBrainz (artist, album) and TMDB (movie, series
  via `tmdb_key.get()`) with *arr optional, and `services/art_search.py` uses
  `services/art_sources` (TMDB, AudioDB, Deezer, iTunes) plus Cover Art Archive
  for albums. Each candidate carries a source tag and a small `preview_url`; one
  source failing still returns the others (a source that cannot answer becomes a
  "did not answer" note, never silence). A TMDB series match gets a TMDB-backed
  refresh so applying it does something without Sonarr.
  Artist and music video artist pictures work with no Lidarr: Deezer
  (`art_sources/deezer.py`, `api.deezer.com/search/artist`, no key, switch
  `DEEZER_ENABLED`) is the keyless artist image source. A hit must equal the
  library name after `art_sources/names.py::match_key` folding (accents, case,
  punctuation, "&" vs "and"; a leading "the" only when nothing matches without
  it), must have a real picture, and the most followed one comes first. TheAudioDB
  uses the free key `123`: the old key `2` is retired and TheAudioDB answers it
  with HTTP 404, which the adapter once swallowed as "no artist"; `audiodb.effective_key`
  still maps a `2` left in an old `.env` to `123`, an artist with a
  MusicBrainz id is looked up by `artist-mb.php`, and any HTTP failure raises
  `AudioDBError`. Never read `settings.audiodb_api_key` for a request without
  `effective_key` (the adapter does it).
- Artist art auto-fill (`services/artist_art_autofill.py`): an artist with no
  `artist` / `thumb` art row gets a picture from TheAudioDB (MBID or exact name)
  then Deezer, saved with `source_kind` `artist_auto`, which only this job
  writes. It is the weakest art there is, like the music-video `frame` grab: it
  never overwrites any existing art row (checked again after the download), and
  every other writer replaces it (the folder scan's sidecar import via
  `scan_library._SCANNER_SOURCES`, the *arr sync via `art._AUTO_SOURCE_KINDS`,
  and every admin upload / URL / search pick). Background job `artist_art_autofill`
  (scheduler): once after boot and queued after every folder scan and music videos
  scan (one job id, so it never stacks; a lock skips a run that overlaps). It
  walks artists in id order in batches, commits per artist, waits
  `ARTIST_ART_AUTOFILL_PAUSE_SEC` (2) after each artist it asked about, remembers
  artists nobody had a picture for in `app_settings` `artist_art_autofill_misses`
  for 30 days (a service error is not remembered, and 5 in a row stop the run),
  and a rerun creates nothing new. Off with `ARTIST_ART_AUTOFILL_ENABLED=false`.
- Artist bios come from Wikipedia through Wikidata. MusicBrainz artists carry a
  `wikidata` url-rel and almost never a `wikipedia` one (checked live on five
  artists), so `services/metadata/wikidata.py` follows MusicBrainz `url-rels` to
  the Wikidata entity, takes its English Wikipedia sitelink, and
  `runner.wikipedia_bio` fetches the page summary extract. `enrich_artist` keeps
  an existing bio when a lookup errors. Background job `artist_bios_backfill`
  (`backfill_artist_bios` in the runner, queued by the scheduler once after boot
  and after each folder scan, one job id so it never stacks, 0.5 s between
  artists, a miss is remembered as `not_found`, a service error is not, five in
  a row stop the run). MusicBrainz and Wikipedia calls use the project
  User-Agent and at most one request a second. The artist page shows the bio in
  the right side of the hero (clamped, More / Less); Home shows a one or two
  sentence excerpt (`services/bio_excerpt.py`, API field `artist_bio_excerpt` on
  album detail) when the featured pick is an album with an artist bio.
- Podcasts (release 1.0.11). `LibraryKind` and `library_folders.KINDS` have
  `podcasts`; its folders are stream roots through the same `libraries` table path
  (`ensure_under_roots`), never a bypass. Tables: `podcasts` (feed or local show),
  `podcast_episodes` (unique per show and guid), `podcast_subscriptions` and
  `podcast_episode_progress` (both per user; one user never reads another's),
  migration `0028_podcasts` (it adds the `podcasts` library_kind and
  `podcast_episode` media_kind values; downgrade leaves them, PostgreSQL cannot
  drop an enum value). Every outbound podcast fetch (feed, chapters JSON,
  enclosure download, enclosure relay, show art) goes through
  `services/net_guard.py`, which also holds the art SSRF check (`art.fetch_url_bytes`
  uses its `open_stream` too, with no loop of its own): on the first request and on
  every redirect hop (at most `MAX_REDIRECTS` = 5) it resolves the host once,
  refuses every address that is not globally routable (`not is_global`, so
  loopback, private, link-local, reserved, unspecified, multicast and the CGNAT /
  Tailscale range 100.64.0.0/10 are all out; an IPv4-mapped IPv6 address is judged
  as the IPv4 address inside it) and then dials only those checked addresses
  through a pinned httpcore backend, so a rebinding name cannot change where the
  connection goes. The URL, the Host header and the TLS server name stay on the
  hostname, so certificate checks are unchanged. Guarded clients set
  `trust_env=False`, so a proxy in the service environment cannot bypass the
  check. `_transport_override` still replaces the network in tests, behind the
  address check. It reads bodies as a stream and stops at the caller's cap
  (feed 20 MB, chapters 2 MB, OPML upload 1 MB, search answer 2 MB), uses 30 s
  connect and read timeouts and the User-Agent `F7FIVE0/<version> (+project URL)`.
  Never fetch a feed-supplied URL any other way. Feeds are parsed by feedparser,
  plus a strict defusedxml pass for the `podcast:` tags; a feed that declares XML
  entities is refused before parsing. Descriptions, titles and chapter titles are
  stored as plain text (`services/podcasts/feed.py::plain_text`: tags and
  script/style removed, entities unescaped); never store or render feed HTML, and
  chapter `img` / `url` are kept only when they are http(s). The browser never
  talks to a publisher: `POST /api/podcasts/episodes/{id}/stream` mints a
  session-bound signed URL (action `podcast`, SEC-P1-2 rules) for
  `/stream/podcast/{episode_id}`, which serves the server file under the stream
  roots with Range, else relays the publisher enclosure with Range passed
  through, nothing written to disk, the guard on every hop, and 415 for anything
  that is not audio (`audio/*`, or an octet-stream with an audio extension). It
  takes only an episode id. The CSP `media-src 'self' blob:` stays as it is.
  Podcast Index search uses `services/podcastindex_key.py`, which mirrors
  `tmdb_key`: the Admin-saved `{key, secret}` (`app_settings` `podcastindex_api`)
  wins over `PODCASTINDEX_API_KEY` / `PODCASTINDEX_API_SECRET`, cached per process
  and refreshed on save; read it only through `podcastindex_key.get()`. Search
  falls back to Apple's iTunes Search API with no key. The secret is never
  returned (the API says `secret_set`), never logged, never in an exception
  message, and the signed headers are never logged. Played = within 30 s of the
  end or past 95 percent, whichever comes first, and never without a known length
  (`services/longform.py`, `frontend/lib/longform.ts`, `mobile/src/player/
  longform.ts`: keep the three in step; they carry no podcast-only names so
  audiobooks can reuse them); skip is back 15 s and forward 30 s; speed is the
  per-user view pref `podcast_speed` (0.5 to 3.0). Progress is per user:
  `PUT /api/podcasts/episodes/{id}/progress` every 15 s while playing and on pause
  and end, buffered offline on the phone (`flushBuffer.ts`, one entry per
  episode). Every save carries `recorded_at_ms` (when the device read the
  position) and a `client` label; the server keeps it as
  `client_recorded_at` (migration 0029), ignores a save taken before the stored
  one (a late retry or an offline replay never moves the place back; a clock
  more than 120 s ahead is held to now + 120 s), and logs one
  `podcast_progress saved|ignored` line per save. Marking played or unplayed
  also stamps it. On the phone the saves come from the playback service
  (`player/service.ts` native events through `podcastProgress.ts`
  `podcastSaverBridge`), never a React effect or the `useProgress` hook, and only
  for the episode the native player has loaded; a save that reaches the server
  clears older buffered saves for that episode, and the buffer also sends when
  the app comes to the front. Feed refresh: a scheduler job every `PODCAST_REFRESH_MINUTES` (60)
  for shows with a subscriber, conditional GET (`ETag` / `Last-Modified`), upsert
  by guid (enclosure URL when there is none), a failed fetch keeps the old
  episodes and sets `last_error`; its state is `app_settings`
  `podcast_refresh_status`, written through `scan_status.py` (`pr_*`) and reset on
  startup if stale. A new episode published after a subscription with
  auto-download on queues a server download. Server downloads
  (`services/podcasts/download.py`) go to the first reachable podcasts folder as
  `<folder>\<show>\<YYYY-MM-DD> <title>.<ext>` through `.part` then a rename,
  with Windows-safe names; `DELETE /api/admin/podcasts/episodes/{id}/download`
  removes only files with `downloaded_by_f7five0` and only under the library
  roots. The folder scan reads the podcasts library (one subfolder per show, one
  audio file per episode; a file already linked to an episode is matched by path
  and never duplicated). There is no storage cap: Admin shows what downloads use
  and the free space on each podcasts folder's drive, and `services/reminders.py`
  raises a banner below `PODCAST_FREE_SPACE_WARN_GB` (10). OPML import
  (`defusedxml`, 1 MB) and export are per user. Video enclosures are listed with
  "Video podcasts aren't supported yet" and never played. The Android Podcasts tab
  is phone only: `mobile/src/screens/tabs.ts` lists the TV tabs and the TV layout
  hides every other route. The phone player switches
  react-native-track-player to jump back 15 s / forward 30 s while an episode
  plays (`player/setup.ts::setPlayerMode`) and never pushes an episode to the
  shared music queue.
- Audio saved while it plays (phone): `mobile/src/download/autoCache.ts` (pure
  policy) and `DownloadProvider` (files under `autocache/`, list in AsyncStorage
  `mh:autocache`, its own one-at-a-time loop apart from Downloads). Every podcast
  episode played from the server is saved, and a music queue saves the playing
  track and the next two. Once an episode's file is saved the player switches to
  it at the current place (the podcast saver is suspended across the switch); a
  later queue track is swapped for its file; the playing music track is never
  switched. Saved copies are not Downloads: the Download button keeps one for good
  and moves the saved file instead of fetching it again. A saved episode goes once
  it counts as played, anything goes 7 days after it was last played, nothing goes
  while the player has it loaded (`setAudioInUse`), and saving pauses below 1 GB
  free. On by default; the switch and the list are on Account > Downloads
  ("Saved while playing"), setting `autoCacheAudio`. `localPathFor` returns a
  download, else a saved copy.
- Auth events: `auth_events.event` is `String(64)` and PostgreSQL enforces it
  (SQLite does not, so a long event passed every test and answered HTTP 500 on
  Admin > Users > Disable). Every event string is built in
  `services/auth_events.py`, and `record_auth_event` is the only writer. It runs
  in a SAVEPOINT and never fails the request. `test_auth_events.py` checks every
  builder and every literal against the column length, so a new event that
  does not fit breaks a test. Never build an event inline.
- Sign-out only on a real 401 from the refresh call. A 5xx, a timeout or a
  dropped connection during token refresh is "try again" (two retries, 0.5 s
  then 1.5 s) and then keeps the session. The decision is the pure helper
  `decideRefresh` in `frontend/lib/refresh-outcome.ts` and
  `mobile/src/api/refreshOutcome.ts`; the web refresh route clears cookies only
  for a 401 from the API. Do not add another path that clears a session on a
  non-401.
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
  the root handler, which rewrites `api_key=<value>` and `token=<value>` (the
  DuckDNS update URL) to `***` in every record (message, arguments and traceback text). A new entry point must call
  `install()`; never log a URL or request that carries a key some other way.
- Scanner-imported art uses `source_kind` `local` or `tmdb`; admin-set art
  (`upload`, `url`, ...) is never overwritten. Weak automatic art (`frame`,
  `artist_auto`) is replaced by the scanner's own art.
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
- Mix art: all 11 mixes on the Mixes page (`random`, `recently-added`,
  `continue-listening`, `most-played`, `never-played`, `recently-played`,
  `artist-random`, `by-year`, `by-decade`, `by-genre`, `artist-radio`) are art
  kind `mix`, role `cover`, with a fixed uuid5 id per key. The first four ids
  shipped first and must never change. Admin sets or resets a picture from the
  mix cards (the Home rail shows the first four); with no override the web shows
  the static default in `frontend/public/mix/<key>.svg`, one per key. Unknown mix
  keys are rejected. Mixes page cards are small (picture 112px, card under
  300px); Home rail cards use `.playbill.compact`.
- Frame-grab thumbs: when a music video has no thumb art, the music videos scan
  grabs one frame with ffmpeg (about 10 percent in) and saves it as
  `music_video` / `thumb` with `source_kind` `frame`. It runs in the scan, never
  in the stream worker. Any other art replaces a frame grab and is never
  replaced by one. Artists get the same treatment from the artist art auto-fill
  job (`source_kind` `artist_auto`, see the Fix Match and art search bullets).
- Movie genres: `enrich_movie` (`services/metadata/runner.py`) saves the TMDB
  genre names to `movies.genres`; it used to leave them to the Radarr sync, so
  installs without Radarr had none and the Movies Genre row showed only All. The
  job `backfill_movie_genres` fills movies that have a TMDB id and no genres
  (batches of 25, a short pause after each lookup, a failed lookup is retried on
  the next run, a second run saves nothing). The scheduler runs it after boot,
  after each folder scan and when a TMDB key is saved.
- Content-Security-Policy `img-src` (`frontend/lib/security-headers.ts`) allows
  `https:`: the art picker shows candidate previews straight from TMDB, iTunes,
  Cover Art Archive and TheAudioDB, and the old allowlist blocked all of them
  (blank tiles). Art candidates carry `preview_url` for the tile and `url` for
  the full image the admin's pick downloads.
- `--bg-2` is not a design token (the v3 tokens define `--bg` and
  `--surface-1..3`), so `background: var(--bg-2)` paints nothing. Use
  `var(--surface-2, #181818)` for an opaque panel. Batch 8 swept the last users
  out of `frontend/`; `git grep bg-2 -- frontend` should stay empty.
- Migrations go through Alembic. Keep revision ids stable: existing installs
  upgrade through them. Register new models in `app/models/__init__.py`.
- Config comes from `.env` at the install root via pydantic-settings. New
  settings need a default, an `.env.example` entry, and (if setup should
  write it) a line in `install.ps1`.
- Signing secrets. In production (`ENVIRONMENT=production`) `config.py` refuses to
  start when `JWT_SECRET` or `STREAM_HMAC_SECRET` is empty, contains `CHANGE_ME`,
  is under 32 characters, or equals the other one (`secret_problems`; the message
  says how to make one and never prints the value). Development and tests only
  warn. `.env.example` ships both blank with the generate command. Setup fills a
  blank or `CHANGE_ME` value in an existing `.env` (`Merge-EnvFile` fill-when-blank
  list: `ARR_WEBHOOK_SECRET`, `JWT_SECRET`, `STREAM_HMAC_SECRET`), never changes a
  real one, and warns about a weak real one (`Get-EnvSecretProblems`).
- Single-use auth transitions are conditional updates, never read-then-write:
  refresh rotation claims the session with `UPDATE sessions ... WHERE revoked_at IS
  NULL RETURNING id`, the grace path with `WHERE grace_used = false`, and a WebAuthn
  challenge with `WHERE consumed_at IS NULL`. The loser of a race takes the reuse
  path (every session revoked, 401) and never mints a second successor.
  `tests/test_pg_concurrency.py` runs real concurrent requests and is opt-in:
  set `F7FIVE0_PG_TEST_URL` to a scratch PostgreSQL database at alembic head (never
  the live one). Run it when touching these paths; SQLite cannot show a race.
- Login throttle (`services/login_throttle.py`): `Retry-After` is the real time
  until enough of the oldest failures in each blocked dimension leave the 15-minute
  window, so waiting it out and signing in works. A blocked attempt is not
  recorded, so hammering never pushes the time later. Check-and-record is
  serialized per username with `pg_advisory_xact_lock` on PostgreSQL (`lock_username`,
  no-op on SQLite), for password and passkey sign-in. The web BFF
  (`/api/session/login`, passkey verify) forwards `Retry-After`; the helpers
  `frontend/lib/login-errors.ts` and `mobile/src/api/throttle.ts` turn it into
  "Too many attempts. Try again in N minutes." (the web page counts down, the phone
  maps 429 to `LoginThrottledError`). The raw `too_many_attempts` code is never shown.
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
- npm audit gate. `scripts/npm_audit_gate.mjs <frontend|mobile>` runs
  `npm audit --omit=dev --json` and fails CI (both the web and the mobile job, after
  `npm ci`) on any high or critical advisory not listed, unexpired, in
  `frontend/npm-audit-exceptions.json` or `mobile/npm-audit-exceptions.json`. An
  entry has an advisory id (or a package), a reason, a scope (`runtime` = ships in
  the app, `build` = tooling on the build machine) and an expiry on or before
  2027-01-06. Expo's build tools (Metro, the Expo CLI, Jest) are in `dependencies`,
  so their advisories sit in the mobile file as `build` exceptions; they retire with
  the Expo SDK upgrade. Never take npm's suggested Expo downgrade, and an `overrides`
  entry must be proven with `npx expo export --platform android` (an `image-size`
  2.x override broke the Metro bundle).
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
  `F7FIVE0-Tunnel` (never touch a pre-existing `Cloudflared` service). One
  tunnel per install: the name is `f7five0-<computer name>` (lowercase), saved
  as `CLOUDFLARE_TUNNEL_NAME` in `.env` and reused on reruns by that install
  only; an install that already runs a tunnel (found from its own
  `cloudflared\config.yml`) keeps it. Setup never fetches credentials for a
  tunnel that has active connectors (`cloudflared tunnel info`) and stops with a
  clear message, and after `route dns --overwrite-dns` it checks where the
  record points and fails if it is another tunnel (cloudflared exits 0 and
  says "already configured to route to your tunnel <id>" without moving it).
  The pure decisions live in `installer/tunnel-logic.ps1` with Pester tests.
  The other methods are a dashboard tunnel token (same service) and Caddy
  (`F7FIVE0-Proxy`, automatic HTTPS, optional DuckDNS name). Never
  offer plain-HTTP port forwarding. The result lands in `.env` as `PUBLIC_URL`;
  the helper restarts API and Web, and clients read it from
  `/api/client/features`.
  `install.ps1 -RemoteAccess <method>` and `remote-access.ps1 -Method` are the
  console (advanced / recovery) paths.
  DuckDNS is refreshed by the API, never by a scheduled task: a hidden
  PowerShell window calling a web URL every 5 minutes is what Defender flagged as
  `Trojan:Win32/Commando.A!ml`, and the task kept the token in plain text.
  `Setup-PortForward` does one update in-process, then saves `DUCKDNS_DOMAIN`
  (subdomain only) and `DUCKDNS_TOKEN` to the private `.env` with `Set-EnvKey`
  (every other method, and off, writes both blank; a rerun for the same name with
  no new token keeps the saved one). The scheduler job `duckdns_refresh` (every 5
  minutes, first run 20 s after boot) exists only when both are set and calls
  `services/duckdns.py`, which sends the User-Agent, treats a body of `OK` as
  success and stores `{checked_at, ok, error}` in `app_settings` `duckdns_status`.
  It never logs the URL or token and keeps exception text out of the status.
  Never add a `Register-ScheduledTask`, `Start-Process` or any new script host
  for this. `Disable-Other` still removes an old `F7FIVE0-DuckDNS` task, and
  `install.ps1` migrates one on upgrade: `Get-DuckDnsFromTaskArgs` (`common.ps1`,
  tested by `installer\tests\duckdns-migrate.ps1`) reads the domain and token out
  of the task arguments, they go to `.env` only where blank, `.env` gets
  `Set-PrivateAcl` again, then the task is unregistered. The token is never printed.
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
- Server addresses in the app (`mobile/src/lib/serverUrl.ts`, pure and unit tested):
  a bare address defaults to `http` only for localhost and loopback, RFC 1918,
  link-local 169.254/16, CGNAT 100.64/10 (Tailscale), `.local` and single-label
  names (`isPrivateHost`); everything else, a public IPv4 address included,
  defaults to `https`. An explicit `http://` to a public host asks for confirmation
  on the sign-in screen before the address is saved or a password is sent
  (`isPublicCleartext`, `cleartextWarning`). Stamped addresses keep the scheme they
  carry.
- Saved library views (which Music browse tab, movie genre and sort, TV
  filter, Music Videos order, Mixes picker values; on the app the hub chips,
  sort/filter and genre) live on the server, per user, in `user_view_prefs`:
  `GET /api/view-prefs` and `PUT /api/view-prefs/{key}` (web through the
  library BFF at `/api/library/view-prefs`). Web pages use `useViewPref` from
  `frontend/lib/use-view-pref.ts` (keys, defaults and allowed values in
  `lib/view-prefs.ts`); the app uses `useViewPref` from
  `mobile/src/state/viewPrefs.ts`. Don't keep view state only in
  localStorage or AsyncStorage; the app's AsyncStorage copy is a cache.
- Poster wall on return (web): the Movies page used to throw its list away on
  unmount, so every return showed placeholders until `/api/library/movies` came
  back (about half the time to the first 20 posters), then rendered the tiles;
  the art itself was already served from the browser cache with no request.
  `frontend/lib/list-cache.ts` keeps the last list in a JS Map for the life of
  the tab (no service worker, IndexedDB or CDN): a copy under 30 s old is
  used with no request, an older one paints first and is then refetched. A
  movie edit (`movies/[id]` `onApplied`) calls `invalidateLists("movies")`; a
  new list page that adopts the cache must do the same for its edits. The
  first 24 posters load eager and the wall's links do not prefetch. Art rules
  above are unchanged.
- Admin-only account creation. No self-serve sign-up.
- Writing style for docs, comments, and commits: plain and direct, no em
  dashes.

## Admin

- `/admin` is an overview dashboard (needs attention, status tiles, streams,
  sessions, recent plays and sign-ins, a settings grid). Each settings area is
  its own page: `/admin/users`, `library-folders`, `scans`, `metadata`, `arr`,
  `audio-analysis`, `remote-access`, `updates` and `activity` (sessions, auth
  events, play history).
- `app/admin/layout.tsx` checks the admin role once (members get "This area is
  limited to administrators") and wraps every admin page in `AuthShell`;
  subpages also get the section list (`components/admin/AdminSectionList.tsx`,
  `aria-current` on the current area). Pages read the signed-in admin with
  `useAdminMe()`.
- The pure rules live in `frontend/lib/admin-dashboard.ts` (no React, no `@/`
  imports, covered by `admin-dashboard.test.ts`): the area list
  (`ADMIN_AREAS`), the old-anchor map (`ADMIN_HASH_MAP`,
  `adminRedirectForHash`, `resolveAdminHref`), the needs-attention rules
  (`buildAttentionItems`), the meter threshold (90 percent warns) and the tile
  summaries. The overview's data and its one shared poll (10 s, 60 s for the
  count tiles, paused while the tab is hidden) are in
  `components/admin/useAdminOverview.ts`; every source fails on its own.
- A new admin area needs a subpage under `app/admin/<area>`, an
  `ADMIN_AREAS` entry (the section list and its tile status in
  `settingsTiles`), a row in `components/admin/SettingsGrid.tsx`, and a hash
  entry in `ADMIN_HASH_MAP` so an old `/admin#<section>` link still lands. The
  backend's reminders still send `/admin#metadata` and
  `/admin#library-folders`; the overview redirects them, so the backend was not
  touched.
- Admin UI uses the v3 tokens only: no raw hex, no `neutral`/`gray`/`zinc`
  classes, `bg-hive` once on the overview (the Update button), red text is
  `text-hive-text`, every status pairs an icon with a word, times and counts
  use `tabular-nums`, touch targets are 44 px. A QR code stays black on white
  (`lib/qr-colors.ts`). The admin no longer folds sections; the
  `admin.collapsed` view pref stays valid so an old stored value still parses.

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
