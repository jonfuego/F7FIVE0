# Native library compatibility (react-native-tvos)

Checked before feature work per spec section 9. Target: **Expo SDK 51 / React
Native 0.74** via the `react-native-tvos` fork, so the same codebase builds the
Android phone and Android TV targets.

## Why SDK 51 / RN 0.74 (not 52 / 0.76)

`react-native-track-player` has **no stable release for RN 0.76** (only
`5.0.0-alpha*`). Its last stable line, `4.1.x`, peer-depends on
`react-native >=0.60` and builds cleanly on RN 0.74. Expo 52 would force RN 0.76
and therefore an alpha track-player, which is not acceptable for the
lock-screen-audio finish line. Expo 51 + `react-native-tvos@0.74.5-0` keeps every
media library on a stable release. This is the single most important pin.

## Pinned versions (all exact, no ^/~)

| Library | Version | Phone | Android TV | Notes |
|---|---|---|---|---|
| expo | 51.0.39 | yes | yes | SDK 51 |
| react | 18.2.0 | yes | yes | |
| react-native (fork) | npm:react-native-tvos@0.74.5-0 | yes | yes | TV + phone from one core |
| @react-native-tvos/config-tv | 0.1.6 | n/a | yes | Adds the TV/leanback manifest at prebuild when EXPO_TV=1 |
| expo-router | 3.5.24 | yes | yes | File-based routes |
| @tanstack/react-query | 5.59.20 | yes | yes | Pure JS; TV-agnostic |
| expo-secure-store | 13.0.2 | yes | yes | Keystore-backed refresh token |
| react-native-track-player | 4.1.2 | yes | see below | Stable; RN 0.74 compatible |
| react-native-video | 6.9.0 | yes | yes | Phone + TV video; peer react-native `*` |
| react-native-safe-area-context | 4.10.5 | yes | yes | |
| react-native-screens | 3.31.1 | yes | yes | |
| react-native-gesture-handler | 2.16.2 | yes | yes | now-playing swipe / router gestures |
| react-native-reanimated | 3.10.1 | yes | yes | |
| expo-file-system | 17.0.1 | yes | yes | Downloads (crit 42/43). NEEDS NATIVE REBUILD (new module). SDK 51 pin. |
| expo-network | 6.0.1 | yes | yes | Offline detection for flush-on-reconnect (crit 43). NEEDS NATIVE REBUILD. SDK 51 pin. |

## Phase 2 (1.2.0) additions

- **expo-file-system 17.0.1** and **expo-network 6.0.1** are new native modules
  added for the download manager + offline mode. Both are the SDK 51-matched
  versions. **A native rebuild (`expo prebuild` + gradle) is required** before
  these work on device — they are config-plugin-free autolinked modules, so no
  app.config plugin entry is needed, but the orchestrator's 1.2.0 build must
  include them. Downloads are stored as files under
  `documentDirectory/downloads/<media_file_id>` (never URLs), so they survive
  signed-URL expiry (crit 43).
- No JS-only Phase 2 dep was added: loudness/lyrics/waveform/track-radio/sort-
  filter/on-deck are all pure-TS + existing libraries (waveform renders with
  plain Views, not react-native-svg, to avoid another native dep).

## Per-library TV findings

- **react-native-track-player 4.1.2** builds on the tvos fork for phone. On
  **Android TV** the foreground-service media notification is not the primary
  surface (TVs drive playback from the remote, not a lock screen), and the
  library's Android build has historically been finicky on leanback. The spec's
  documented fallback is honored: **on TV, audio playback uses
  `react-native-video` instead of track-player** (see `src/video/VideoPlayer.tsx`;
  the TV screens route audio through the video wrapper). Phone audio uses
  track-player for true background/lock-screen playback. If track-player's TV
  build proves clean on the target hardware, TV audio can be switched back to it
  with no API change to the player provider.
- **react-native-video 6.9.0** supports Android phone and Android TV, including
  D-pad-driven controls. Used for all video on both targets and for audio on TV.
- **expo-secure-store 13.0.2** uses the Android Keystore on both phone and TV.
- **@react-native-tvos/config-tv 0.1.6** is what injects
  `android.intent.category.LEANBACK_LAUNCHER` and the TV feature flags into the
  Android manifest during `EXPO_TV=1 npx expo prebuild`.

## Verification

`npm run verify` is green on this set: `tsc --noEmit` reports 0 errors,
eslint 0 errors, and jest 19/19 (see `reports/tsc.log`, `reports/eslint.log`,
`reports/jest.json`). The Android phone release APK builds and signs from this
set (see `reports/apksigner-phone.txt` and `reports/apk-contents-phone.txt`).

## 2026-09-27 validation additions

- **Local Expo module `modules/f7five0-auto`** (autolinked from `./modules` by
  expo-modules-autolinking 1.11.3): Android-only `F7FIVE0BrowserService`
  (`androidx.media:media:1.6.0` `MediaBrowserServiceCompat` +
  `MediaSessionCompat`) so Android Auto can browse and control playback.
  react-native-track-player 4.1.2's `MusicService` is a `HeadlessJsTaskService`,
  not a media browser service, so it can't serve a car browse tree by itself.
  Written without a local Android compiler; first confirmed by `fixup-build.ps1`.
- No new npm packages. `expo-modules-core` (already installed via `expo`) is
  imported for `requireOptionalNativeModule`, so the bridge is a no-op on TV and
  in jest.
