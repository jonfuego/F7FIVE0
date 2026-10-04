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

Official releases put the matching APK on the server for you (see Official
releases below). To offer your own build instead, copy it into the server's
`C:\F7FIVE0\data\downloads\` folder as `F7FIVE0-<version>.apk` (the newest
version wins). Everyone then sees **Download for Android** on their Account
page, and each download is stamped with the server's addresses.

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
The release key does not live on GitHub. The server and the phone app ship
as one version: Setup.exe carries the matching APK and copies it onto the
server. Bump `version` and `versionCode` in `app.config.ts` to the release
version, then from the repo root:

```powershell
.\scripts\release-apk.ps1 -Version 1.0.0                    # 64-bit, required
.\scripts\release-apk.ps1 -Version 1.0.0 -Abi armeabi-v7a   # 32-bit, optional
git tag v1.0.0
git push origin v1.0.0
```

`release-apk.ps1` refuses to build without the keystore properties file,
builds a release APK for one ABI (`arm64-v8a` unless `-Abi` says otherwise),
checks the APK's signer against the keystore certificate (and rejects the
debug key) and that it carries only that ABI's native code, stages
`mobile\dist\F7FIVE0-<version>.apk` (or `-armv7.apk`) plus a `.sha256`,
prints the certificate SHA-256 and the passkey app origin, then uploads both
files to a draft GitHub release for the tag (created if needed). Pushing the
tag runs the Release workflow, which downloads the APK(s) from the draft,
checks the `.sha256`, bundles them into Setup.exe and the zip, and publishes
the release. No APK on the draft means no release. `-NoUpload` stops after
staging; `-Tv` builds the Android TV variant (every ABI unless `-Abi` is
given), which is not bundled.

## Server-stamped downloads

A server stamps every APK it hands out with its addresses: one extra entry in
the APK Signing Block, which the signature does not cover, so the APK stays
validly signed and installs over the official app
(`backend/app/services/apk_stamp.py`). On first launch the local module
`modules/f7five0-stamp` reads the entry back from the installed APK, and
`src/state/config.ts` uses the first address that answers. Copies built
locally or taken from GitHub have no stamp and ask for the address.

If you build the app yourself, it is signed with your own key, so it
installs as a separate app from the official one and cannot update it.

## Passkeys

The sign-in screen offers **Sign in with passkey** when the server address is
https and the server has passkeys on (`/api/client/features`). Account >
Passkeys adds, renames, and removes them. Android TV builds never show it.

The app's passkey origin is its signing certificate, so the server must list
that certificate. Official builds work with every server by default. If you
sign the app with your own key, put your certificate's SHA-256 (printed by
`scripts\release-apk.ps1`, or `keytool -list -v`) in the server's
`WEBAUTHN_ANDROID_CERT_SHA256`.

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
