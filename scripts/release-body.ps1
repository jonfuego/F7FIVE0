# Build the text of a GitHub release page (the release "body").
#
# Called by .github/workflows/release.yml ("Attach and publish") and runnable
# here to preview a release page before tagging:
#
#   pwsh scripts/release-body.ps1 -Version 1.0.24 -OutFile notes.md
#
# The body has three parts, in this order:
#   1. The plain-language notes for this version, from release-notes/<ver>.md.
#      Admin > Updates shows only this part, under "What's new". A missing or
#      empty file never stops a release: a short fallback line goes in instead.
#   2. The marker line below. The Updates page cuts the body here, so nothing
#      after it ever shows in the app. Keep it identical to RELEASE_NOTES_MARKER
#      in frontend/lib/release-notes.ts.
#   3. The "Which file do I need?" download guide, then GitHub's generated notes
#      (the change list and the Full Changelog link), for the release page.
#
# The signing sentence follows -Signed: "signed" only when the sign step
# checked a Valid signature, so the page never calls an unsigned Setup.exe
# signed (or the reverse).
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repo = "jonfuego/F7FIVE0",
    [string]$Signed = "",
    [string]$Generated = "",
    [string]$NotesDir = "",
    [Parameter(Mandatory = $true)][string]$OutFile
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Marker = "<!-- f7five0:download-guide -->"

if (-not $NotesDir) { $NotesDir = Join-Path (Split-Path -Parent $PSScriptRoot) "release-notes" }
$notesFile = Join-Path $NotesDir "$Version.md"

$userNotes = ""
if (Test-Path -LiteralPath $notesFile -PathType Leaf) {
    $userNotes = (Get-Content -LiteralPath $notesFile -Raw -Encoding utf8)
    if ($null -eq $userNotes) { $userNotes = "" }
    # The marker inside the notes would cut them short in the app.
    $userNotes = $userNotes.Replace($Marker, "").Trim()
}
if (-not $userNotes) {
    Write-Host "release-notes/$Version.md is missing or empty; using the fallback line."
    $userNotes = "No release notes were written for this version. The full list of changes is on the release page."
} else {
    Write-Host "Using release-notes/$Version.md."
}

# A "which file" guide goes above GitHub's change list, so people who land on
# the release page download Setup.exe, not the zip or the APK.
$guide = @'
## Which file do I need?

| File | What it is |
|---|---|
| `F7FIVE0-Setup-X.Y.Z.exe` | **The Windows installer. Most people need only this file.** Run it on the PC that will be your media server. |
| `F7FIVE0-X.Y.Z.apk` | The Android phone app. It installs on a phone, not on Windows. Easier: once your server is running, sign in from your phone's browser and use **Account > Download for Android**. |
| `F7FIVE0-X.Y.Z.zip` | The same server files without the wizard, for installing from PowerShell. See "Installing without the wizard" in INSTALL.md. |
| `SHA256SUMS.txt` | Checksums for the installer and the zip. |
| `sbom-*.cdx.json` | Software bill of materials. |

Setup needs a 64-bit Windows 10 (1809 or newer) or Windows 11 PC, an administrator account, and an internet connection. {SIGNING} Full guide: [INSTALL.md](https://github.com/{REPO}/blob/vX.Y.Z/INSTALL.md).

[Code signing policy](https://github.com/{REPO}/blob/vX.Y.Z/docs/code-signing-policy.md) | [Privacy](https://github.com/{REPO}/blob/vX.Y.Z/PRIVACY.md)
'@
$signing = if ($Signed -eq "true") {
    'Setup is code-signed through SignPath Foundation; Windows shows the publisher when it starts.'
} else {
    'Setup is not code-signed yet, so Windows may show "Windows protected your PC": choose **More info**, then **Run anyway**.'
}
$guide = $guide.Replace("X.Y.Z", $Version).Replace("{REPO}", $Repo).Replace("{SIGNING}", $signing)

$parts = @($userNotes, $Marker, $guide.Trim())
$gen = ($Generated | Out-String).Trim()
if ($gen) { $parts += $gen }
$body = ($parts -join "`n`n").Replace("`r`n", "`n") + "`n"

# UTF-8 without a byte order mark, in Windows PowerShell 5.1 and in pwsh alike.
$full = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).Path, $OutFile))
[System.IO.File]::WriteAllText($full, $body, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Wrote $full"
