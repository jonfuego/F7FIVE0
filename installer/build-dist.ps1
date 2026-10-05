<#
.SYNOPSIS
  Builds the release payload that Setup.exe and the release zip ship.

.DESCRIPTION
  Produces installer\dist\ with this layout (the same layout install.ps1
  installs into C:\F7FIVE0):

    backend\     FastAPI source + requirements.txt (no venv, no tests)
    web\         Next.js standalone bundle, ready for `node server.js`
    installer\   install.ps1 / uninstall.ps1 / remote-access.ps1 / common.ps1
    android\     F7FIVE0-<version>.apk (+ -armv7) and .sha256 files, when
                 -ApkDir is given. install.ps1 copies them into data\downloads.
    alembic.ini  .env.example  LICENSE  README.md  INSTALL.md  VERSION

  Then, if Inno Setup is installed (or -Compile is passed), compiles
  installer\Output\F7FIVE0-Setup-<version>.exe.

  Needs Node.js 20+ on PATH. Used by the GitHub release workflow and handy
  locally:  pwsh .\installer\build-dist.ps1 -Version 1.0.0
#>
[CmdletBinding()]
param(
    [string] $Version = "0.0.0-dev",
    [switch] $Compile,
    [switch] $SkipWebBuild,
    # Folder holding the signed phone APK(s) from scripts\release-apk.ps1 and
    # their .sha256 files. Release builds pass it (the workflow downloads them
    # from the draft release); -RequireApk makes a missing APK fatal.
    [string] $ApkDir = "",
    [switch] $RequireApk
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dist = Join-Path $PSScriptRoot "dist"
$Frontend = Join-Path $Repo "frontend"

function Mirror([string]$from, [string]$to, [string[]]$xd = @(), [string[]]$xf = @()) {
    $extra = @()
    if ($xd.Count) { $extra += @("/XD") + $xd }
    if ($xf.Count) { $extra += @("/XF") + $xf }
    & robocopy $from $to /MIR /NFL /NDL /NJH /NJS /NC /NS /NP @extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $from -> $to failed ($LASTEXITCODE)" }
}

if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
New-Item -ItemType Directory -Path $Dist | Out-Null

if (-not $SkipWebBuild) {
    Push-Location $Frontend
    try {
        $env:NEXT_TELEMETRY_DISABLED = "1"
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "next build failed" }
    } finally { Pop-Location }
}
$standalone = Join-Path $Frontend ".next\standalone"
if (-not (Test-Path (Join-Path $standalone "server.js"))) { throw "no standalone build at $standalone" }
Mirror $standalone (Join-Path $Dist "web")
Mirror (Join-Path $Frontend ".next\static") (Join-Path $Dist "web\.next\static")
Mirror (Join-Path $Frontend "public") (Join-Path $Dist "web\public")

Mirror (Join-Path $Repo "backend") (Join-Path $Dist "backend") @(".venv", "__pycache__", ".pytest_cache", "tests", "_reports") @("*.pyc")
Mirror (Join-Path $Repo "scripts") (Join-Path $Dist "scripts") @() @("dev-*.ps1", "publish.ps1")
New-Item -ItemType Directory -Path (Join-Path $Dist "installer") | Out-Null
foreach ($f in @("install.ps1", "uninstall.ps1", "common.ps1", "remote-access.ps1")) {
    Copy-Item (Join-Path $PSScriptRoot $f) (Join-Path $Dist "installer\$f")
}
# The Apps list icon (UninstallDisplayIcon in F7FIVE0.iss) points at the
# installed copy, so ship the generated .ico next to the installer scripts.
# The wizard images and the Setup.exe icon are compiled into Setup.exe and are
# not needed at runtime. All of these come from installer\branding-src\, which
# renders them from design\logos; the files in installer\branding\ are committed.
$brandIco = Join-Path $PSScriptRoot "branding\f7five0.ico"
if (Test-Path $brandIco) { Copy-Item $brandIco (Join-Path $Dist "installer\f7five0.ico") }
foreach ($f in @("alembic.ini", ".env.example", "LICENSE", "README.md", "INSTALL.md")) {
    $s = Join-Path $Repo $f
    if (Test-Path $s) { Copy-Item $s (Join-Path $Dist $f) }
}
Set-Content -Path (Join-Path $Dist "VERSION") -Value $Version -NoNewline -Encoding ASCII

# Android app. Phone builds only (F7FIVE0-<x.y.z>.apk and -armv7); TV builds
# are a separate download. Every APK needs a matching .sha256 file.
$apkCount = 0
if ($ApkDir) {
    if (-not (Test-Path $ApkDir)) { throw "APK folder not found: $ApkDir" }
    $androidOut = Join-Path $Dist "android"
    New-Item -ItemType Directory -Path $androidOut | Out-Null
    foreach ($apk in Get-ChildItem $ApkDir -Filter "F7FIVE0-*.apk" -File) {
        if ($apk.Name -notmatch '^F7FIVE0-\d+\.\d+\.\d+(-armv7)?\.apk$') { continue }
        $shaFile = "$($apk.FullName).sha256"
        if (-not (Test-Path $shaFile)) { throw "missing $($apk.Name).sha256" }
        $want = ((Get-Content $shaFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
        $got = (Get-FileHash $apk.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($want -ne $got) { throw "$($apk.Name) checksum mismatch (file $got, .sha256 $want)" }
        Copy-Item $apk.FullName (Join-Path $androidOut $apk.Name)
        Copy-Item $shaFile (Join-Path $androidOut "$($apk.Name).sha256")
        Write-Host "android: $($apk.Name) ($([math]::Round($apk.Length / 1MB)) MB, checksum ok)"
        $apkCount++
    }
}
$hasPhone = $apkCount -gt 0 -and (Get-ChildItem (Join-Path $Dist "android") -Filter "F7FIVE0-*.apk" | Where-Object { $_.Name -notmatch '-armv7\.apk$' })
if ($RequireApk -and -not (Test-Path (Join-Path $Dist "android\F7FIVE0-$Version.apk"))) {
    throw "No F7FIVE0-$Version.apk to bundle. The server and app ship as one version: run scripts\release-apk.ps1 -Version $Version first."
}
if (-not $hasPhone) { Write-Host "android: no APK bundled; the server will not offer the Android app." }
Write-Host "dist ready: $Dist"

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($iscc) {
    $numeric = ($Version -replace '[^0-9.].*$', '')
    if (-not $numeric) { $numeric = "0.0.0" }
    & $iscc "/DAppVersion=$Version" "/DAppVersionNumeric=$numeric" (Join-Path $PSScriptRoot "F7FIVE0.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }
} elseif ($Compile) {
    throw "Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) and re-run."
} else {
    Write-Host "Inno Setup not found; skipped Setup.exe. The dist folder can be zipped and installed with installer\install.ps1."
}
