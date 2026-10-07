<#
.SYNOPSIS
  Updates F7FIVE0 from a Setup that the web app has already verified. Runs as
  the SYSTEM scheduled task F7FIVE0-Update; an admin starts it from
  Admin > Updates.

.DESCRIPTION
  The web app (backend\app\services\updates.py) downloads or accepts a Setup,
  checks it, writes <install>\data\updates\request.json, and starts the task.
  This script treats that request as untrusted input and does the rest:

    1. verifying     The Setup must sit directly inside data\updates\incoming,
                     its SHA-256 must equal the request, and for source "signed"
                     its Authenticode signature must be Valid from the signer in
                     .env. The same or a lower version than version.json is
                     refused, and so is an install with no cached Setup of the
                     installed version (a failed update could not go back).
                     The Setup is copied into data\updates\run (Administrators
                     and SYSTEM only) and the copy is what is checked and run, so
                     nobody can swap the file between the check and the run.
    2. backup        Stops the services and writes pg_dump -Fc of the F7FIVE0
                     database to data\updates\backup\<from>-<id>.dump. A new
                     version can run Alembic migrations, so the code alone is not
                     enough to go back.
    3. installing    Runs the Setup: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
                     /SP- /LOG=<logs>\update-<id>-setup.log
    4. health_check  Within 5 minutes /api/health must report the new version,
                     /stream/health must answer 200, and the web port must answer
                     200.
    5. rolling_back  When any step after the backup fails: stop the services,
                     pg_restore --clean the dump, run the cached Setup of the
                     version that was installed (same silent flags), and
                     health-check that version.

  Progress goes to data\updates\status.json (phase, step, error, log path, and
  the phases passed), which the Admin page polls. The file is written about
  every 5 seconds while a long step runs, so it also tells the page the updater
  is alive across the services restarting. The log is logs\update-<id>.log.

  Phases end in done, rolled_back, or failed. Exit code: 0 done, 2 rolled back,
  1 failed, 3 nothing to do.

  This file is copied to data\updates\run\ by install.ps1, and the task runs the
  copy: Setup replaces the install folder while this script is running.

.PARAMETER InstallDir
  The F7FIVE0 install folder. Default C:\F7FIVE0.

.PARAMETER FromRequest
  Read data\updates\request.json (what the scheduled task passes).

.PARAMETER PgBin
  Folder holding pg_dump.exe and pg_restore.exe. Default: the newest
  PostgreSQL under Program Files. (Used by installer\tests\update-verify.ps1.)

.PARAMETER HealthTimeoutSeconds
  How long to wait for the health checks. Default 300.
#>
[CmdletBinding()]
param(
    [string] $InstallDir = "C:\F7FIVE0",
    [switch] $FromRequest,
    [string] $PgBin = "",
    [int]    $HealthTimeoutSeconds = 300
)

# Windows PowerShell 5.1 compatible, ASCII only. Run elevated or as SYSTEM.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$DataDir     = Join-Path $InstallDir "data"
$UpdDir      = Join-Path $DataDir "updates"
$Incoming    = Join-Path $UpdDir "incoming"
$SetupCache  = Join-Path $UpdDir "setup"
$BackupDir   = Join-Path $UpdDir "backup"
$RunDir      = Join-Path $UpdDir "run"
$LogsDir     = Join-Path $InstallDir "logs"
$EnvFile     = Join-Path $InstallDir ".env"
$VersionFile = Join-Path $InstallDir "version.json"
$StatusFile  = Join-Path $UpdDir "status.json"
$RequestFile = Join-Path $UpdDir "request.json"
$ServiceNames = @("F7FIVE0-Web", "F7FIVE0-Stream", "F7FIVE0-API")

. (Join-Path $PSScriptRoot "common.ps1")

# ---------------------------------------------------------------------------
# Status and log
# ---------------------------------------------------------------------------
function Now-Iso { return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }

$script:Status = [ordered]@{
    id = ""; phase = "queued"; from_version = ""; to_version = ""; source = ""; step = ""
    error = $null; error_code = $null; started_at = (Now-Iso); updated_at = (Now-Iso); finished_at = $null
    log = ""; phases = @()
}

function Save-Status {
    $script:Status.updated_at = Now-Iso
    $json = $script:Status | ConvertTo-Json -Depth 4
    $tmp = "$StatusFile.$([Guid]::NewGuid().ToString('N').Substring(0, 8)).tmp"
    for ($i = 0; $i -lt 5; $i++) {
        try {
            [IO.File]::WriteAllText($tmp, $json, (New-Object Text.UTF8Encoding($false)))
            Move-Item -LiteralPath $tmp -Destination $StatusFile -Force
            return
        } catch { Start-Sleep -Milliseconds 100 }
    }
}

function Add-PhaseName([string]$phase) {
    $list = @($script:Status.phases)
    if ($list.Count -eq 0 -or $list[$list.Count - 1] -ne $phase) { $list += $phase }
    $script:Status.phases = $list
}

function Set-Phase([string]$phase, [string]$step) {
    $script:Status.phase = $phase
    $script:Status.step = $step
    Add-PhaseName $phase
    Save-Status
    Info "[$phase] $step"
}

function Set-Step([string]$step) {
    $script:Status.step = $step
    Save-Status
}

function Finish-Run([string]$phase, [string]$err = "", [string]$code = "") {
    $script:Status.phase = $phase
    $script:Status.step = $null
    $script:Status.error = if ($err) { $err } else { $null }
    $script:Status.error_code = if ($code) { $code } else { $null }
    $script:Status.finished_at = Now-Iso
    Add-PhaseName $phase
    Save-Status
    if ($err) { Warn $err } else { Ok "update finished: $phase" }
}

# Stops the run with an error code (the admin page words it). Thrown from any step.
function Refuse([string]$code, [string]$message) {
    $ex = New-Object System.Exception($message)
    $ex.Data["code"] = $code
    throw $ex
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Get-InstalledVersion {
    try {
        $j = Get-Content -Raw -LiteralPath $VersionFile | ConvertFrom-Json
        if ($j.version -and (Test-SemVer ([string]$j.version))) { return ([string]$j.version).Trim() }
    } catch { }
    return "0.0.0-dev"
}

function Get-EnvPort([string]$key, [int]$fallback) {
    $v = Get-EnvValue $key
    if ($v -match '^\d+$') { return [int]$v }
    return $fallback
}

function Stop-F7Services {
    foreach ($n in $ServiceNames) {
        $s = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($s -and $s.Status -ne "Stopped") { Info "stop $n"; Stop-Service -Name $n -Force -ErrorAction SilentlyContinue }
    }
    $deadline = (Get-Date).AddSeconds(60)
    foreach ($n in $ServiceNames) {
        $s = Get-Service -Name $n -ErrorAction SilentlyContinue
        if (-not $s) { continue }
        while ($s.Status -ne "Stopped" -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500; $s.Refresh() }
    }
}

function Start-F7Services {
    foreach ($n in @("F7FIVE0-API", "F7FIVE0-Stream", "F7FIVE0-Web")) {
        $s = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($s -and $s.Status -ne "Running") { Info "start $n"; Start-Service -Name $n -ErrorAction SilentlyContinue }
    }
}

function Find-PgTool([string]$name) {
    if ($PgBin) {
        $p = Join-Path $PgBin "$name.exe"
        if (Test-Path -LiteralPath $p) { return $p }
        return $null
    }
    $roots = @(Get-ChildItem "$env:ProgramFiles\PostgreSQL" -Directory -ErrorAction SilentlyContinue | Sort-Object { [int]($_.Name -replace '\D', '0') } -Descending)
    foreach ($r in $roots) {
        $p = Join-Path $r.FullName "bin\$name.exe"
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

# User, password, host, port, and database name from DATABASE_URL in .env.
function Get-DbInfo {
    $url = Get-EnvValue "DATABASE_URL"
    $ok = $url -match '^postgres(?:ql)?(?:\+\w+)?://([^:/@]+)(?::([^@]*))?@([^:/]+)(?::(\d+))?/([^?\s]+)'
    if (-not $ok) {
        Refuse "no_database_url" "Couldn't read the database settings from .env, so no backup could be made."
    }
    $port = 5432
    if ($matches[4]) { $port = [int]$matches[4] }
    $password = ""
    if ($matches[2]) { $password = [Uri]::UnescapeDataString([string]$matches[2]) }
    return @{
        User = [Uri]::UnescapeDataString([string]$matches[1])
        Password = $password
        Host = [string]$matches[3]
        Port = $port
        Name = [string]$matches[5]
    }
}

# Runs a native tool without letting stderr become a terminating error.
# The database password goes in PGPASSWORD, never on the command line.
function Invoke-Pg([string]$exe, [string[]]$toolArgs, [string]$password) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $env:PGPASSWORD = $password
    try {
        & $exe @toolArgs 2>&1 | ForEach-Object { Write-RunLog "$_" }
        return [int]$LASTEXITCODE
    } finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
        $ErrorActionPreference = $prev
    }
}

# Runs a Setup silently and returns its exit code. Touches status.json every few
# seconds while it works, so the admin page can tell it is still alive.
function Invoke-Setup([string]$exe, [string]$setupLog) {
    $setupArgs = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="{0}" /LOG="{1}"' -f $InstallDir, $setupLog
    Info "run $([IO.Path]::GetFileName($exe)) $setupArgs"
    $p = Start-Process -FilePath $exe -ArgumentList $setupArgs -PassThru -WindowStyle Hidden
    $null = $p.Handle
    $deadline = (Get-Date).AddMinutes(45)
    while (-not $p.WaitForExit(5000)) {
        Save-Status
        if ((Get-Date) -gt $deadline) {
            try { $p.Kill() } catch { }
            return 124
        }
    }
    return [int]$p.ExitCode
}

# Probes one URL: $null when it answers 200 (and, for the API, reports the
# expected version), otherwise a short reason.
function Test-Url([string]$url, [string]$expectVersion = "") {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0 -ErrorAction Stop
    } catch {
        $resp = $_.Exception.Response
        if ($resp) { return "HTTP $([int]$resp.StatusCode) from $url" }
        return "no answer from $url"
    }
    if ([int]$r.StatusCode -ne 200) { return "HTTP $([int]$r.StatusCode) from $url" }
    if ($expectVersion) {
        $reported = ""
        try { $reported = [string]((ConvertFrom-Json $r.Content).version) } catch { }
        if ($reported -ne $expectVersion) { return "the API reports version '$reported', not '$expectVersion'" }
    }
    return $null
}

# Waits for the API (right version), the stream gateway, and the web app.
$script:HealthReason = ""
function Wait-Healthy([string]$version, [int]$seconds) {
    $apiPort = Get-EnvPort "API_PORT" 8001
    $streamPort = Get-EnvPort "STREAM_PORT" 8002
    $webPort = Get-EnvPort "WEB_PORT" 3001
    $deadline = (Get-Date).AddSeconds($seconds)
    while ($true) {
        $reason = Test-Url "http://127.0.0.1:$apiPort/api/health" $version
        if (-not $reason) { $reason = Test-Url "http://127.0.0.1:$streamPort/stream/health" }
        if (-not $reason) { $reason = Test-Url "http://127.0.0.1:$webPort/login" }
        if (-not $reason) { $script:HealthReason = ""; return $true }
        $script:HealthReason = $reason
        if ((Get-Date) -ge $deadline) { return $false }
        Set-Step "Waiting for F7FIVE0 $version to come up ($reason)"
        Start-Sleep -Seconds 3
    }
}

# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
if (-not $FromRequest) {
    Write-Host "update.ps1 is started by the F7FIVE0-Update task. Use Admin > Updates, or pass -FromRequest."
    exit 3
}
New-Item -ItemType Directory -Force -Path $UpdDir, $RunDir, $LogsDir | Out-Null
if (-not (Test-Path -LiteralPath $RequestFile)) {
    Write-Host "No update request. Nothing to do."
    exit 3
}

# One update at a time, for the life of this process.
$lock = $null
try {
    $lock = [IO.File]::Open((Join-Path $RunDir "update.lock"), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
} catch {
    Write-Host "Another update is running."
    exit 3
}

# Read the request once, then remove it so a second start can't replay it.
$request = $null
try { $request = Get-Content -Raw -LiteralPath $RequestFile | ConvertFrom-Json } catch { }
Remove-Item -LiteralPath $RequestFile -Force -ErrorAction SilentlyContinue

$id = if ($request -and ([string]$request.id) -match '^[0-9a-f]{32}$') { [string]$request.id } else { [Guid]::NewGuid().ToString("N") }
$from = Get-InstalledVersion
$to = if ($request -and (Test-SemVer ([string]$request.version))) { ([string]$request.version).TrimStart('v') } else { "" }
$source = if ($request) { [string]$request.source } else { "" }

# Carry over what the web app already recorded for this run (queued, started_at).
try {
    $prior = Get-Content -Raw -LiteralPath $StatusFile | ConvertFrom-Json
    if ($prior.id -eq $id) {
        $script:Status.started_at = [string]$prior.started_at
        $script:Status.phases = @($prior.phases | Where-Object { $_ })
    }
} catch { }
$script:Status.id = $id
$script:Status.from_version = $from
$script:Status.to_version = $to
$script:Status.source = $source
$script:Status.log = Join-Path $LogsDir "update-$id.log"
$script:RunLog = $script:Status.log
$script:FailPrefix = "F7FIVE0 update stopped"

$exitCode = 1
$staged = $null
$dump = $null
$installStarted = $false
$stopped = $false
try {
    Info "update $from -> $to ($source), request $id"
    Set-Phase "verifying" "Checking the Setup"
    if (-not $request) { Refuse "bad_request" "The update request couldn't be read." }
    if (-not $to) { Refuse "bad_request" "The request has no valid version." }
    if (([string]$request.sha256) -notmatch '^[0-9a-fA-F]{64}$') { Refuse "bad_request" "The request has no valid SHA-256." }
    if (@("github", "release", "signed") -notcontains $source) { Refuse "bad_request" "The request's source '$source' isn't one this updater accepts." }

    # Never the same version, never an older one. A prerelease sorts below its release.
    if ((Compare-SemVer $to $from) -le 0) {
        Refuse "not_newer" "Version $to is not newer than the installed $from. F7FIVE0 never installs the same or an older version."
    }

    # The Setup must be a file directly inside incoming\, found by its full path.
    $full = [IO.Path]::GetFullPath([string]$request.setup_path)
    $incomingFull = [IO.Path]::GetFullPath($Incoming).TrimEnd('\')
    if (-not ([IO.Path]::GetDirectoryName($full) -ieq $incomingFull)) {
        Refuse "outside_incoming" "The Setup is not inside $incomingFull, so it was refused."
    }
    if ([IO.Path]::GetFileName($full) -ine "F7FIVE0-Setup-$to.exe") {
        Refuse "bad_name" "The Setup's file name doesn't match version $to, so it was refused."
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { Refuse "missing_setup" "The Setup file is not there: $full" }
    if ((Get-Item -LiteralPath $full -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Refuse "outside_incoming" "The Setup is a link, not a file inside $incomingFull, so it was refused."
    }

    # No way back means no update: the cached Setup of the installed version is
    # what a rollback runs.
    $previousSetup = Join-Path $SetupCache "F7FIVE0-Setup-$from.exe"
    if (-not (Test-Path -LiteralPath $previousSetup -PathType Leaf)) {
        Refuse "no_rollback_copy" "There is no cached Setup for the installed version ($from), so a failed update couldn't be rolled back. Run the new Setup by hand once; it keeps a copy for next time."
    }
    $pgDump = Find-PgTool "pg_dump"
    $pgRestore = Find-PgTool "pg_restore"
    if (-not $pgDump -or -not $pgRestore) { Refuse "no_pg_tools" "pg_dump or pg_restore wasn't found, so no database backup could be made." }
    $db = Get-DbInfo

    # Work on a private copy: check it, run it. Nothing can swap it in between.
    $staged = Join-Path $RunDir "F7FIVE0-Setup-$to.exe"
    Copy-Item -LiteralPath $full -Destination $staged -Force
    $got = (Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($got -ne ([string]$request.sha256).ToLowerInvariant()) {
        Refuse "hash_mismatch" "The Setup's SHA-256 ($got) doesn't match the request, so it was refused."
    }
    if ($source -eq "signed") {
        $sig = Get-AuthenticodeSignature -LiteralPath $staged
        $subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
        $want = Get-EnvValue "UPDATE_SIGNER_SUBJECT"
        $norm = { param($s) (($s -replace '\s*,\s*', ', ').Trim()).ToLowerInvariant() }
        if ($sig.Status -ne "Valid" -or -not $want -or (& $norm $subject) -ne (& $norm $want)) {
            Refuse "bad_signature" "The Setup's Authenticode signature isn't Valid from the configured signer (status '$($sig.Status)', signer '$subject'), so it was refused."
        }
    }
    Ok "Setup checked: $to ($($got.Substring(0, 12))...)"

    # --- backup ---------------------------------------------------------------
    Set-Phase "backup" "Backing up the database"
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $dump = Join-Path $BackupDir "$from-$id.dump"
    Stop-F7Services
    $stopped = $true
    $rc = Invoke-Pg $pgDump @("-w", "-h", $db.Host, "-p", "$($db.Port)", "-U", $db.User, "-d", $db.Name, "-Fc", "-f", $dump) $db.Password
    if ($rc -ne 0 -or -not (Test-Path -LiteralPath $dump) -or (Get-Item -LiteralPath $dump).Length -eq 0) {
        Refuse "backup_failed" "The database backup failed (pg_dump exit $rc), so nothing was changed."
    }
    Ok "database backed up: $dump"

    # --- install --------------------------------------------------------------
    Set-Phase "installing" "Installing F7FIVE0 $to"
    $installStarted = $true
    $env:F7FIVE0_UPDATE_RUN = $id
    $setupRc = Invoke-Setup $staged (Join-Path $LogsDir "update-$id-setup.log")
    if ($setupRc -ne 0) { throw "Setup exited with code $setupRc (see logs\update-$id-setup.log)." }

    # --- health check ---------------------------------------------------------
    Set-Phase "health_check" "Waiting for F7FIVE0 $to to come up"
    if (-not (Wait-Healthy $to $HealthTimeoutSeconds)) { throw "the health check failed: $script:HealthReason" }

    Finish-Run "done"
    $exitCode = 0
}
catch {
    $code = ""
    try { $code = [string]$_.Exception.Data["code"] } catch { }
    $message = $_.Exception.Message
    if (-not $installStarted) {
        # Nothing was installed: the install is as it was. Bring the services back if we stopped them.
        if ($stopped) { try { Start-F7Services } catch { } }
        Finish-Run "failed" $message $(if ($code) { $code } else { "update_failed" })
        $exitCode = 1
    } else {
        # Something went wrong after the backup: go back to the version that was running.
        Warn "The update to $to did not work: $message"
        try {
            Set-Phase "rolling_back" "Going back to $from"
            Stop-F7Services
            $rc = Invoke-Pg $pgRestore @("-w", "-h", $db.Host, "-p", "$($db.Port)", "-U", $db.User, "-d", $db.Name, "--clean", "--if-exists", "--no-owner", "--no-privileges", $dump) $db.Password
            if ($rc -ne 0) { throw "pg_restore exited with code $rc" }
            Ok "database restored from $dump"
            $env:F7FIVE0_UPDATE_RUN = $id
            $rbRc = Invoke-Setup $previousSetup (Join-Path $LogsDir "update-$id-rollback-setup.log")
            if ($rbRc -ne 0) { throw "the previous Setup exited with code $rbRc" }
            if (-not (Wait-Healthy $from $HealthTimeoutSeconds)) { throw "the old version didn't come up: $script:HealthReason" }
            Finish-Run "rolled_back" "The new version ($to) did not come up: $message F7FIVE0 went back to $from and restored the database from the backup. Your data is as it was before the update."
            $exitCode = 2
        } catch {
            Finish-Run "failed" "The update to $to failed ($message) and going back to $from failed too ($($_.Exception.Message)). The database backup is $dump and the previous Setup is $previousSetup. Run that Setup by hand, or restore the backup with pg_restore --clean." "rollback_failed"
            $exitCode = 1
        }
    }
}
finally {
    Remove-Item Env:\F7FIVE0_UPDATE_RUN -ErrorAction SilentlyContinue
    # The private copy and the file in incoming\ are done with, whatever happened.
    foreach ($leftover in @($staged, $(if ($request) { [string]$request.setup_path } else { "" }))) {
        if ($leftover -and (Test-Path -LiteralPath $leftover -PathType Leaf)) {
            $parent = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($leftover))
            if ($parent -ieq [IO.Path]::GetFullPath($RunDir).TrimEnd('\') -or $parent -ieq [IO.Path]::GetFullPath($Incoming).TrimEnd('\')) {
                Remove-Item -LiteralPath $leftover -Force -ErrorAction SilentlyContinue
            }
        }
    }
    # Keep the two newest backups; each is a full dump of the database.
    try {
        $dumps = @(Get-ChildItem $BackupDir -Filter "*.dump" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
        for ($i = 2; $i -lt $dumps.Count; $i++) { Remove-Item -LiteralPath $dumps[$i].FullName -Force -ErrorAction SilentlyContinue }
    } catch { }
    if ($lock) { $lock.Dispose() }
}
exit $exitCode
