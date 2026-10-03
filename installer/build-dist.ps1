<#
.SYNOPSIS
  Builds the release payload that Setup.exe and the release zip ship.

.DESCRIPTION
  Produces installer\dist\ with this layout (the same layout install.ps1
  installs into C:\F7FIVE0):

    backend\     FastAPI source + requirements.txt (no venv, no tests)
    web\         Next.js standalone bundle, ready for `node server.js`
    installer\   install.ps1 / uninstall.ps1 / remote-access.ps1 / common.ps1
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
    [switch] $SkipWebBuild
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
foreach ($f in @("alembic.ini", ".env.example", "LICENSE", "README.md", "INSTALL.md")) {
    $s = Join-Path $Repo $f
    if (Test-Path $s) { Copy-Item $s (Join-Path $Dist $f) }
}
Set-Content -Path (Join-Path $Dist "VERSION") -Value $Version -NoNewline -Encoding ASCII
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
