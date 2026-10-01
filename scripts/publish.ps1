# Build and deploy F7FIVE0 from the git tree to the runtime root.
#
# Default flow:
#   1. git pull --ff-only in the repo root so an SSH session can redeploy
#      without a separate pull step. Bails on a dirty tree or non-ff.
#      If the pull changes frontend\package*.json or backend\requirements.txt,
#      the corresponding dep install runs automatically at the right step.
#   2. Verify prerequisites (node, python venv, nssm, target layout).
#   3. Build the frontend (npm run build in frontend\). If npm deps changed,
#      runs npm ci first.
#   4. Assemble the Next standalone bundle (static + public copied into
#      .next\standalone\, because the Next build doesn't do this itself).
#   5. Snapshot the current runtime to $Target\releases\<timestamp>\ so a
#      rollback is one rename away.
#   6. Stop the three F7FIVE0 services.
#   7. Robocopy frontend -> $Target\web\ and backend -> $Target\backend\.
#      /MIR mirrors, so deletions from source reach the target.
#      If requirements.txt changed, runs pip install against the runtime venv.
#   7b. Copy alembic.ini from the repo root to $Target\alembic.ini so that
#       `cd $Target; alembic upgrade head` resolves the relative
#       script_location path to backend\alembic\.
#   8. Start the services.
#
# Safe to re-run. If a build fails, the old runtime is untouched.
#
# Flags:
#   -Target <path>   Runtime root. Default C:\F7FIVE0.
#   -SkipPull        Don't run git pull. Useful when iterating locally or
#                    running against an intentionally-pinned checkout.
#   -SkipBuild       Reuse the existing .next\ output. Useful for debugging
#                    the copy step without a full rebuild.
#   -SkipSwap        Build and copy, but do not stop/start services.
#                    Useful when doing a staged verification before cutover.
#   -Only <subset>   Deploy only one side. Accepts "web" or "backend".

[CmdletBinding()]
param(
    [string] $Target = "C:\F7FIVE0",
    [switch] $SkipPull,
    [switch] $SkipBuild,
    [switch] $SkipSwap,
    [ValidateSet("web", "backend", "all")]
    [string] $Only = "all"
)

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $RepoRoot "frontend"
$Backend  = Join-Path $RepoRoot "backend"

$Node = (Get-Command node -ErrorAction SilentlyContinue).Source
$Npm  = (Get-Command npm  -ErrorAction SilentlyContinue).Source
$Nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
# The installer keeps its own nssm.exe under <Target>\bin.
if (-not $Nssm -and (Test-Path (Join-Path $Target "bin\nssm.exe"))) { $Nssm = Join-Path $Target "bin\nssm.exe" }
$Git  = (Get-Command git  -ErrorAction SilentlyContinue).Source

if (-not $Node) { throw "node not found on PATH" }
if (-not $Npm)  { throw "npm not found on PATH" }
if (-not $Nssm) { throw "nssm not found on PATH" }
if (-not $SkipPull -and -not $Git) { throw "git not found on PATH (pass -SkipPull to skip the pull step)" }

if (-not (Test-Path $Target)) {
    throw "runtime root $Target does not exist. Run installer\install.ps1 to bootstrap it first."
}

$WebTarget      = Join-Path $Target "web"
$BackendTarget  = Join-Path $Target "backend"
$ReleasesDir    = Join-Path $Target "releases"
$LogsDir        = Join-Path $Target "logs"

foreach ($d in @($WebTarget, $BackendTarget, $ReleasesDir, $LogsDir)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d | Out-Null
    }
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Info($msg) {
    Write-Host "    $msg" -ForegroundColor DarkGray
}

# Pull the latest from origin first. This is the "one SSH command" path:
# log in, run publish.ps1, walk away. --ff-only bails loudly rather than
# silently creating a merge or rebase commit on a drifting server checkout.
#
# After the pull, diff the before/after commits so we know whether to run
# npm ci (when lock/package.json changed) or pip install (when
# requirements.txt changed). These flags default to $false so -SkipPull or
# an already-up-to-date tree skips both installs cleanly.
$NeedsNpmInstall = $false
$NeedsPipInstall = $false

if (-not $SkipPull) {
    Step "Pulling latest from git"
    Push-Location $RepoRoot
    try {
        $status = & $Git status --porcelain
        if ($status) {
            Write-Host $status -ForegroundColor Yellow
            throw "working tree at $RepoRoot has local changes. Commit/stash them or pass -SkipPull."
        }
        $branch = (& $Git rev-parse --abbrev-ref HEAD).Trim()
        $before = (& $Git rev-parse HEAD).Trim()
        Info "branch=$branch before=$($before.Substring(0,12))"
        & $Git pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            throw "git pull --ff-only failed ($LASTEXITCODE). Local and remote have diverged; resolve manually."
        }
        $after = (& $Git rev-parse HEAD).Trim()
        if ($before -eq $after) {
            Info "already up to date"
        } else {
            Info "after=$($after.Substring(0,12))"
            # git always emits forward slashes in --name-only output.
            $changed = @(& $Git diff --name-only $before $after)
            if ($changed -contains "frontend/package.json" -or
                $changed -contains "frontend/package-lock.json") {
                $NeedsNpmInstall = $true
                Info "frontend deps changed; will npm ci before build"
            }
            if ($changed -contains "backend/requirements.txt") {
                $NeedsPipInstall = $true
                Info "backend requirements changed; will pip install after copy"
            }
        }
    } finally {
        Pop-Location
    }
}

# Frontend build
if ($Only -in @("all", "web") -and -not $SkipBuild) {
    Push-Location $Frontend
    try {
        if ($NeedsNpmInstall) {
            Step "Installing frontend deps (npm ci)"
            & $Npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed ($LASTEXITCODE)" }
        }
        Step "Building frontend"
        & $Npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed ($LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

# Assemble the standalone bundle. Next 14 standalone output only contains
# server.js plus node_modules needed to run it. Static assets (.next\static\)
# and public\ are deliberately not copied so you can deploy them to a CDN.
# For a self-hosted install, we want everything in one folder.
if ($Only -in @("all", "web")) {
    Step "Assembling standalone bundle"
    $Standalone = Join-Path $Frontend ".next\standalone"
    $Static     = Join-Path $Frontend ".next\static"
    $Public     = Join-Path $Frontend "public"
    if (-not (Test-Path $Standalone)) {
        throw "standalone bundle not found at $Standalone. Run 'npm run build' (or drop -SkipBuild)."
    }
    $StandaloneStatic = Join-Path $Standalone ".next\static"
    $StandalonePublic = Join-Path $Standalone "public"
    if (-not (Test-Path (Split-Path $StandaloneStatic))) {
        New-Item -ItemType Directory -Path (Split-Path $StandaloneStatic) | Out-Null
    }
    robocopy $Static $StandaloneStatic /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy static -> standalone failed ($LASTEXITCODE)" }
    if (Test-Path $Public) {
        robocopy $Public $StandalonePublic /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy public -> standalone failed ($LASTEXITCODE)" }
    }
    Info "standalone ready at $Standalone"
}

# Snapshot current runtime before overwriting. Rollback is a rename swap.
if (-not $SkipSwap) {
    Step "Snapshotting current runtime to releases\$Stamp\"
    $SnapRoot = Join-Path $ReleasesDir $Stamp
    New-Item -ItemType Directory -Path $SnapRoot | Out-Null
    if ($Only -in @("all", "web") -and (Get-ChildItem $WebTarget -Force -ErrorAction SilentlyContinue)) {
        robocopy $WebTarget     (Join-Path $SnapRoot "web")     /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    }
    if ($Only -in @("all", "backend") -and (Get-ChildItem $BackendTarget -Force -ErrorAction SilentlyContinue)) {
        # Skip .venv in the snapshot. It's GB-sized and recreatable from requirements.txt.
        robocopy $BackendTarget (Join-Path $SnapRoot "backend") /E /NFL /NDL /NJH /NJS /NC /NS /NP /XD ".venv" "__pycache__" | Out-Null
    }
    Info "snapshot -> $SnapRoot"
}

# Stop services before swapping. Windows holds file handles on running .js
# and .py files under NSSM and robocopy will fail.
if (-not $SkipSwap) {
    Step "Stopping services"
    $toStop = @()
    if ($Only -in @("all", "web"))     { $toStop += "F7FIVE0-Web" }
    if ($Only -in @("all", "backend")) { $toStop += "F7FIVE0-API", "F7FIVE0-Stream" }
    foreach ($svc in $toStop) {
        $svcObj = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if (-not $svcObj) {
            Info "$svc not installed, skipping"
            continue
        }
        # nssm stop on an already-stopped service exits non-zero, and under
        # PowerShell 5.1 the *>$null redirect doesn't fully swallow it, which
        # aborted the whole publish. Check status first and skip the stop
        # call when the service is already down.
        if ($svcObj.Status -eq 'Stopped') {
            Info "$svc already stopped, skipping"
            continue
        }
        Info "stop $svc"
        & $Nssm stop $svc *>$null
    }
}

# Copy new artifacts into place.
if ($Only -in @("all", "web")) {
    Step "Deploying web -> $WebTarget"
    $Standalone = Join-Path $Frontend ".next\standalone"
    robocopy $Standalone $WebTarget /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy web -> target failed ($LASTEXITCODE)" }
}

if ($Only -in @("all", "backend")) {
    Step "Deploying backend -> $BackendTarget"
    # /MIR would delete the .venv on the target because it's not in source.
    # Use /E (recurse) and /XD to hold .venv and logs back.
    robocopy $Backend $BackendTarget /E /NFL /NDL /NJH /NJS /NC /NS /NP `
        /XD ".venv" "__pycache__" "logs" `
        /XF "*.pyc" | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy backend -> target failed ($LASTEXITCODE)" }

    # alembic.ini lives at the repo root because its script_location is the
    # relative path backend/alembic. Mirror it to $Target so that running
    # `cd $Target; alembic upgrade head` finds the config without a hand copy.
    $AlembicIni = Join-Path $RepoRoot "alembic.ini"
    if (Test-Path $AlembicIni) {
        Copy-Item -LiteralPath $AlembicIni -Destination (Join-Path $Target "alembic.ini") -Force
        Info "alembic.ini deployed to $Target"
    } else {
        Info "alembic.ini not present at repo root; skipping"
    }

    Info "backend source deployed; .venv at target left intact"

    if ($NeedsPipInstall) {
        # requirements.txt changed in this pull. Update the runtime venv now,
        # while services are stopped, so the new module set is on disk before
        # uvicorn restarts. Pip is invoked directly from the venv so we don't
        # depend on PATH ordering.
        $VenvPip = Join-Path $BackendTarget ".venv\Scripts\pip.exe"
        if (-not (Test-Path $VenvPip)) {
            throw "pip not found at $VenvPip. Recreate the venv: python -m venv $BackendTarget\.venv"
        }
        $Reqs = Join-Path $BackendTarget "requirements.txt"
        Step "Installing backend deps"
        & $VenvPip install -r $Reqs
        if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }
    }
}

# Start services back up.
if (-not $SkipSwap) {
    Step "Starting services"
    $toStart = @()
    if ($Only -in @("all", "backend")) { $toStart += "F7FIVE0-API", "F7FIVE0-Stream" }
    if ($Only -in @("all", "web"))     { $toStart += "F7FIVE0-Web" }
    foreach ($svc in $toStart) {
        if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
            Info "start $svc"
            # nssm writes "SERVICE_START_PENDING" to stderr when a service
            # takes a moment to come up. Under PowerShell 5.1 that stderr
            # becomes a terminating error (ErrorActionPreference=Stop), which
            # aborted the loop and left later services stopped. Merge stderr
            # into the success stream and swallow it; verify via Get-Service.
            try { & $Nssm start $svc 2>&1 | Out-Null } catch { Info "$svc start: $_" }
        }
    }
}

Write-Host ""
Write-Host "Publish complete." -ForegroundColor Green
Write-Host "Snapshot: $(Join-Path $ReleasesDir $Stamp)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Rollback if needed:" -ForegroundColor Yellow
Write-Host "  nssm stop F7FIVE0-Web F7FIVE0-API F7FIVE0-Stream"
Write-Host "  robocopy $(Join-Path $ReleasesDir $Stamp)\web     $WebTarget     /MIR"
Write-Host "  robocopy $(Join-Path $ReleasesDir $Stamp)\backend $BackendTarget /E /XD .venv"
Write-Host "  nssm start F7FIVE0-API F7FIVE0-Stream F7FIVE0-Web"
