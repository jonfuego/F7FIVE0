# F7FIVE0 parity checklist

> Created 2026-09-30, revised same day after reviewing the F7FIVE0 repo.
> arcHIVE is retired when every box in sections 1 to 11 is checked.
> arcHIVE feature reference: Fuego-HQ vault `projects/mediahub/overview.md`, `history.md`, and the 1.2.0 spec `handoffs/mediahub-2-app-parity_task_v2.md`.
> Copies: vault `Fuego-HQ/projects/f7five0/` and repo `F7FIVE0/docs/`. Keep them in sync.

Legend: `[x]` = present in the F7FIVE0 code (checked by reading the repo on 2026-09-30, not yet smoke-tested on a fresh F7FIVE0 install). `[ ]` = missing or not confirmed.

## Decisions (2026-09-30)

- arcHIVE is frozen: bug fixes only, no new features.
- F7FIVE0 is a standalone, self-hosted product with its own backend, web app, Android app, and Windows installer. It does not share arcHIVE's backend. Jon runs the same build users install.
- All new features go to F7FIVE0 only. Podcasts are the first F7FIVE0-only feature.
- When this list is complete: move Jon's install from arcHIVE to F7FIVE0, repoint media.fuegofam.com, archive the arcHIVE repos.

## Status at a glance

F7FIVE0 was forked from arcHIVE at about 1.2.0 (Alembic head 0021). The parity gaps are:

1. ~~Passkey sign-in~~ Ported 2026-09-30 (migration 0022, same revision id). Code-verified and browser-tested, not yet on a real install or phone. See `f7five0_passkeys-plan_v1.md` in the vault.
2. ~~Chromecast in the Android app.~~ Ported 2026-10-01 from arcHIVE app 1.3.0 (`f5e48a8`, `b6dcc6e`, `f4e095e`, `ca2c270`). tsc and jest pass; not yet tested with a real Chromecast.
3. F7FIVE0 design system. Tokens v2, Tailwind preset and RN theme are in `design/` but not wired in; web and mobile still use arcHIVE fonts (Bebas, Fraunces). Archivo is not used yet.
4. Install, cutover and data migration (sections 10 and 11).
5. ~~Mobile library lists capped at 200 rows.~~ Ported 2026-10-01 from arcHIVE app `c7ac7a6` (full lists, A-Z rail jumps by grid row). tsc and jest pass; not yet checked on a device.

## 1. Access and accounts

- [x] Password sign-in (web, phone, TV)
- [x] Passkey (fingerprint) sign-in, app and web (2026-09-30; on only with an https PUBLIC_URL; real-device check pending)
- [x] Device sessions (native sessions, migration 0020)
- [x] Account page: display name, password
- [x] Admin-only account creation

## 2. Browse

- [x] Home: hero, Continue Watching, On Deck, Recent Arrivals, Mixes preview
- [x] Movies, TV (seasons, episodes), music (artists, albums, songs), music videos
- [x] Mixes / auto-playlists
- [x] A to Z rail
- [x] Android app library lists load the whole library, not the first 200 (2026-10-01, from arcHIVE `c7ac7a6`)
- [x] Sort on library screens
- [x] Search
- [x] Artwork: local files first, TMDB and MusicBrainz, admin art overrides never overwritten

## 3. Music playback

- [x] Queue with server sync, track-play logging
- [x] Gapless, crossfade
- [x] Loudness leveling (EBU R128)
- [x] Lyrics (embedded and .lrc)
- [x] Similar-track / artist radio
- [x] Waveform scrubber
- [x] Sleep timer, playback speed
- [ ] Background audio and lock-screen controls: confirm on device

## 4. Video playback

- [x] Direct play and HLS transcode (NVENC when present)
- [x] Resume, mark watched / unwatched
- [x] Skip intro, skip credits, next episode
- [x] Subtitle and audio track pickers, quality picker (signed track-opts)
- [ ] Transcoding on non-NVIDIA hardware (QuickSync, AMD, CPU): confirm acceptable

## 5. Casting

- [x] Chromecast from the web app
- [x] Chromecast from the Android app (video and music queue) (2026-10-01; phone only, TV build excluded; real-device check pending, including casting while signed in over a plain-http LAN address)

## 6. Offline

- [x] Downloads for offline playback (Android)
- [ ] Offline mode and sync-on-reconnect: confirm on device

## 7. Requests

- [x] Request search and create, My Requests (needs Radarr/Sonarr; `/api/client/features` tells clients)

## 8. Platforms

- [x] Web (installable PWA)
- [x] Android phone
- [x] Android TV / Fire TV (`app-tv/` screens)
- [x] Android Auto (`modules/f7five0-auto`)

## 9. Admin

- [x] Admin page
- [ ] Confirm parity with arcHIVE admin: sessions, auth events, health, request approve / deny, edit modal (overrides, sort title, fix match), art overrides, rescan

## 10. Design

- [ ] Wire `design/` tokens v2 into the web app (Tailwind preset, Archivo)
- [ ] Wire the RN theme v2 into the Android phone, TV and Auto app
- [ ] Logo rule applied everywhere: black and red mark only; on white-needed surfaces, place it in a white box

## 11. Install and cutover

- [x] Windows installer: Setup.exe (Inno Setup), `install.ps1`, uninstall, build-dist, CI release on `v*` tags
- [x] Remote access options: Tailscale Funnel, Cloudflare named tunnel, Caddy with HTTPS
- [ ] Clean-VM install test passes (per repo CLAUDE.md, required before tagging)
- [ ] Signed Android release builds and a documented update path
- [ ] Data migration tool, arcHIVE to F7FIVE0: users, passwords, watch progress, queues, track plays, requests, metadata and art overrides, audio analysis (or re-run backfill)
- [ ] Jon's own install moved to F7FIVE0 and smoke-tested
- [ ] media.fuegofam.com repointed (and decide on mediaapi.fuegofam.com)
- [ ] Invited users moved to the F7FIVE0 app
- [ ] arcHIVE repos (ArcHive, mediahub-app) archived; release keystore backed up first

## Beyond parity (F7FIVE0 only, not required to retire arcHIVE)

- [ ] Podcasts
- [ ] iPhone / iPad
- [ ] Apple TV

## Test plan notes (2026-09-30)

- Test hostname: `f750.fuegofam.com` (Jon: "F750.fuegofam.com"). Never enter `media.fuegofam.com` in F7FIVE0 setup while arcHIVE is live: the Cloudflare option runs `route dns --overwrite-dns`.
- Side by side with arcHIVE on the same PC: `install.ps1 -WebPort 3101 -ApiPort 8101 -StreamPort 8102` (ports configurable as of 2026-09-30; setup stops if a port is taken).
- Clean-VM install test first (VirtualBox), then side-by-side on Jon's box, then switchover rehearsal.

## Backlog ideas

- Easter eggs alluding to the name: F7FIVE0 / F750 is a response to Plex raising the lifetime Plex Pass price. What exactly is still open.
