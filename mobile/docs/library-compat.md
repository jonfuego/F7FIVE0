# Native library compatibility (react-native-tvos)

Target: **Expo SDK 54 / React Native 0.81** via the `react-native-tvos` fork
(`0.81.5-2`), on the **old architecture** (`newArchEnabled: false` in
`app.config.ts`), so the same codebase builds the Android phone and Android TV
targets. Upgraded from SDK 51 / RN 0.74 on 2026-10-03.

## Why SDK 54 on the old architecture

SDK 54 is the last Expo SDK that still supports the old architecture; SDK 55+
(RN 0.82+) is New Architecture only. `react-native-track-player` still has no
stable New Architecture release (4.1.2 is the last stable line; 5.x is alpha),
so the app stays on the old architecture for now. The next step (SDK 55+)
needs track-player, google-cast, passkey, video, and the local Expo modules
proven on New Architecture first.

SDK 51 to 54 notes:

- `react-native-track-player` 4.1.2 fails to compile under Kotlin 2.x
  (`Bundle?` passed to `Arguments.fromBundle`). `patches/` carries the fix,
  applied by `patch-package` on `npm install` (upstream issue #2579).
- `react-native-reanimated` stays on 3.x: 4.x requires New Architecture.
  `package.json` `expo.install.exclude` keeps `expo install --fix` from
  bumping it.
- The Kotlin stdlib pin plugin (`withKotlinStdlibPin`) is gone: SDK 54 builds
  with Kotlin 2.1, which reads the stdlib androidx.credentials pulls in.
- `expo-file-system`'s classic API moved to `expo-file-system/legacy`.
- Android is always edge-to-edge (targetSdk 36); check insets on device.
- Bottom tabs: `sceneContainerStyle` became `screenOptions.sceneStyle`.
- ESLint 9 flat config (`eslint.config.js`, `eslint-config-expo/flat`).
- Node 20.19.4 or newer is required.

## Pinned versions (all exact, no ^/~)

| Library | Version | Phone | Android TV | Notes |
|---|---|---|---|---|
| expo | 54.0.37 | yes | yes | SDK 54 |
| react | 19.1.0 | yes | yes | |
| react-native (fork) | npm:react-native-tvos@0.81.5-2 | yes | yes | TV + phone from one core |
| @react-native-tvos/config-tv | 0.1.7 | n/a | yes | Adds the TV/leanback manifest at prebuild when EXPO_TV=1 |
| expo-router | 6.0.24 | yes | yes | File-based routes |
| @tanstack/react-query | 5.59.20 | yes | yes | Pure JS; TV-agnostic |
| expo-secure-store | 15.0.8 | yes | yes | Keystore-backed refresh token |
| react-native-track-player | 4.1.2 (patched) | yes | see below | Old architecture only |
| react-native-video | 6.19.3 | yes | yes | Phone + TV video |
| react-native-google-cast | 4.9.1 | yes | n/a | Phone sender only |
| react-native-passkey | 3.6.2 | yes | yes | |
| react-native-safe-area-context | 5.6.2 | yes | yes | |
| react-native-screens | 4.16.0 | yes | yes | |
| react-native-gesture-handler | 2.28.0 | yes | yes | now-playing swipe / router gestures |
| react-native-reanimated | 3.19.5 | yes | yes | 3.x for the old architecture |
| expo-file-system | 19.0.24 | yes | yes | Downloads, through `expo-file-system/legacy` |
| expo-network | 8.0.8 | yes | yes | Offline detection for flush-on-reconnect |

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
