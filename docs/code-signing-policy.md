# F7FIVE0 code signing policy

This page describes how the F7FIVE0 Windows installer is signed, who signs it,
what gets signed, and how anyone can reproduce the build. It is the policy page
that SignPath Foundation requires for an open source signing project.

## Project

- Project: F7FIVE0, a self-hosted media server for Windows.
- Source: https://github.com/jonfuego/F7FIVE0 (public, Unlicense / public domain).
- Maintainer and signer of record: Jon Fourneau (the sole maintainer).

## Who signs

Authenticode signing of the Windows installer is performed by SignPath
Foundation on behalf of the project. The maintainer does not hold the private
key. SignPath holds the certificate and performs the signing operation inside
its service. No signing private key, certificate, or key password is stored in
this repository or anywhere in the build environment.

The Android release key is a separate matter and is NOT covered by SignPath. The
Android APK is signed locally by the maintainer with a key that never leaves the
maintainer's machine and is never uploaded to GitHub or CI. See the release
notes in `scripts/release-apk.ps1` and `.github/workflows/release.yml`.

## What is signed

- `F7FIVE0-Setup-<version>.exe`, the Inno Setup installer produced by the
  release workflow. This is the only artifact submitted to SignPath.

The following are published but are NOT Authenticode signed:

- The release zip (`F7FIVE0-<version>.zip`), which is a plain archive of the
  same payload for operators who prefer a manual install.
- The Android APKs, which carry their own Android app signature (see above).

Every published release also ships integrity material so downloads can be
verified independently of any signature:

- `SHA256SUMS.txt`, SHA-256 checksums of the Setup.exe and the zip.
- CycloneDX software bills of materials: `sbom-backend.cdx.json` (from the
  hash-pinned backend lock), `sbom-web.cdx.json` (web app), and
  `sbom-mobile.cdx.json` (mobile app).

## How builds are produced

Builds are produced by a GitHub Actions workflow, not on a developer machine,
so the path from public source to signed binary is auditable:

- Workflow: `.github/workflows/release.yml`, job `windows-installer`, running on
  the GitHub-hosted `windows-latest` runner.
- Trigger: pushing a `v*` tag (a real release) or a manual `workflow_dispatch`
  (a test build that is never published).
- Every `uses:` action in the workflow is pinned to a full 40-character commit
  SHA, so the toolchain is fixed.
- The backend is installed only from `backend/requirements.lock`, an exact,
  hash-pinned resolution, with `pip install --require-hashes`.
- Every file the installer downloads at install time is pinned to an exact
  version, an immutable URL, and a SHA-256 in
  `installer/downloads.manifest.psd1`.

Order of operations in the release job:

1. Build the web bundle and assemble the install payload
   (`installer/build-dist.ps1`).
2. Compile `F7FIVE0-Setup-<version>.exe` with Inno Setup.
3. Submit the Setup.exe to SignPath for Authenticode signing and replace it with
   the signed copy. This step runs only when a `SIGNPATH_API_TOKEN` secret is
   configured; when it is absent the step is skipped and the release ships an
   unsigned installer.
4. Create the release zip.
5. Generate the three CycloneDX SBOMs.
6. Write `SHA256SUMS.txt` over the Setup.exe and the zip.
7. Upload the Setup.exe, the zip, the SBOMs, and `SHA256SUMS.txt` to the
   release.

## How to reproduce a build

Anyone can reproduce the unsigned installer locally from a clean checkout at the
release tag. Signing is the only step that cannot be reproduced outside
SignPath, by design, because it needs the private key SignPath holds.

Prerequisites: Windows, Node.js 20 or newer, Python 3.12, and Inno Setup 6
(`winget install JRSoftware.InnoSetup`).

```powershell
git clone https://github.com/jonfuego/F7FIVE0
cd F7FIVE0
git checkout v<version>
pwsh .\installer\build-dist.ps1 -Version <version> -Compile
```

This writes `installer\Output\F7FIVE0-Setup-<version>.exe` and a
`SHA256SUMS.txt` next to it, plus a `SHA256SUMS.txt` over the assembled payload
in `installer\dist\`. The SHA-256 of a locally built Setup.exe will match the
published one when the same tag, toolchain versions, and pinned downloads are
used; the published Setup.exe additionally carries the SignPath Authenticode
signature.

## Reporting

Suspected misuse of the signing certificate, or a signed binary that does not
match a public tag, should be reported by opening an issue on the repository.
