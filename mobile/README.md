# F7FIVE0 for Android

One Expo (React Native) codebase builds the phone app, the Android TV app,
and Android Auto support. It talks to any F7FIVE0 server: users type the
server address on the sign-in screen, the same address they use in a
browser.

## Build an APK

Needs Node.js 22, JDK 17, and the Android SDK (Android Studio installs both).

```powershell
cd mobile
npm ci
npx expo prebuild -p android --clean
cd android
.\gradlew assembleRelease
# -> android\app\build\outputs\apk\release\app-release.apk
```

Android TV build: set `$env:EXPO_TV = "1"` before `expo prebuild`.

To offer the APK to your users, copy it into your server's
`C:\F7FIVE0\data\downloads\` folder (any name ending in `.apk`; the newest
wins). Everyone then sees **Download for Android** on their Account page.

## Signing

Android only installs updates signed with the same key as the first
install, so make one key and keep it safe:

```powershell
keytool -genkeypair -v -keystore $HOME\.f7five0-keys\release.jks -alias f7five0 -keyalg RSA -keysize 2048 -validity 10000
```

Then create `$HOME\.f7five0-keys\keystore.properties`:

```
storeFile=C:/Users/<you>/.f7five0-keys/release.jks
storePassword=...
keyAlias=f7five0
keyPassword=...
```

`plugins/withAndroidReleaseSigning.js` picks it up on every prebuild (or
point `F7FIVE0_KEYSTORE_PROPERTIES` at another location). Without it,
release builds use React Native's debug key: fine for trying things, not
for handing out.

Bump `android.versionCode` in `app.config.ts` for every APK you hand out,
or Android refuses it as an update.

Back up `release.jks` and `keystore.properties` somewhere offline. If the key
is lost, installed apps can never be updated; users must uninstall and
reinstall.

## Official releases

Official F7FIVE0 APKs are signed on the maintainer's machine, never in CI.
The release key does not live on GitHub. After pushing a `v*` tag and letting
the Release workflow publish Setup.exe and the zip, run from the repo root:

```powershell
.\scripts\release-apk.ps1 -Version 1.0.0
```

It refuses to build without the keystore properties file, builds the
release APK, checks the APK's signer against the keystore certificate (and
rejects the debug key), stages `mobile\dist\F7FIVE0-<version>.apk` plus a
`.sha256`, prints the certificate SHA-256 and the passkey app origin, then
attaches both files to the GitHub release with `gh`. `-NoUpload` stops
after staging; `-Tv` builds the Android TV variant.

If you build the app yourself, it is signed with your own key, so it
installs as a separate app from the official one and cannot update it.

A build can ship with a default server by setting
`EXPO_PUBLIC_API_BASE=https://media.example.com` before prebuild.

## Develop and test

```powershell
npm run typecheck
npm test
npm run lint
npx expo run:android      # dev build on a device or emulator
```

End-to-end flows in `e2e/` (phone) and `e2e-tv/` (TV) use
[Maestro](https://maestro.mobile.dev). They sign in as a member account
named `native-smoke`:

```powershell
# On the server, once:
cd C:\F7FIVE0\backend
.\.venv\Scripts\python.exe -m app.cli create-admin --username native-smoke --name "Native Smoke" --role member

# Then, with an emulator running (10.0.2.2 is the host PC from the emulator):
maestro test -e F7FIVE0_SERVER=http://10.0.2.2:3001 -e SMOKE_PASSWORD=<password> e2e
```

`docs/library-compat.md` explains the pinned library versions (Expo SDK 51
with react-native-tvos 0.74 so phone and TV share one core).
