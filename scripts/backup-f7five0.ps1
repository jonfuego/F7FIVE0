<#
.SYNOPSIS
  Nightly backup of everything in F7FIVE0 that cannot be regenerated:
  the Postgres database (users, watch progress, overrides, playlists) plus
  the locally-owned art and metadata-cache bytes.

  Media files themselves are NOT backed up: back those up however you
  already do. This covers what only F7FIVE0 knows.

.DESCRIPTION
  Steps:
    1. Source DB credentials from C:\F7FIVE0\.env (same parse as
       never hardcoded).
    2. Read BACKUP_DEST from C:\F7FIVE0\.env. Fail loudly if unset.
    3. pg_dump the database in custom format (-Fc) to
       <BACKUP_DEST>\db\f7five0-<timestamp>.dump
    4. robocopy /MIR the art and metadata-cache directories to
       <BACKUP_DEST>\art and <BACKUP_DEST>\metadata-cache
    5. Retention: delete *.dump older than 14 days.

  Restore the database from a dump with:
    pg_restore --clean --if-exists --no-owner -d <db_url> <file.dump>
  (stop the F7FIVE0 services first; pg_restore --list <file.dump> shows
  the archive contents without restoring).

.NOTES
  Runs unattended via the F7FIVE0-Backup scheduled task
  (scripts\register-backup-task.ps1). Logs to logs\f7five0-backup.log
  next to this scripts folder.
#>
[CmdletBinding()]
param(
    [string] $EnvFile      = 'C:\F7FIVE0\.env',
    [int]    $RetentionDays = 14
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LogDir   = Join-Path $RepoRoot 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile  = Join-Path $LogDir 'f7five0-backup.log'

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

if (-not (Test-Path $EnvFile)) { throw "env file not found: $EnvFile" }
$envText = Get-Content $EnvFile -Raw

# --- DB credentials (same pattern as use-f7five0-db.ps1) ---
$dbUrl = ([regex]::Match($envText, '(?m)^DATABASE_URL=(.*)$')).Groups[1].Value.Trim()
if ($dbUrl -notmatch 'postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(\S+)') {
    throw "could not parse DATABASE_URL from $EnvFile"
}
$pgUser = $matches[1]; $pgPass = $matches[2]; $pgHost = $matches[3]
$pgPort = if ($matches[4]) { $matches[4] } else { '5432' }
$pgDb   = $matches[5]

# --- BACKUP_DEST ---
$dest = ([regex]::Match($envText, '(?m)^BACKUP_DEST=(.*)$')).Groups[1].Value.Trim()
if ([string]::IsNullOrWhiteSpace($dest)) {
    throw "BACKUP_DEST is not set in $EnvFile. Add it (e.g. BACKUP_DEST=\\nas\backup\f7five0 or E:\Backups\f7five0) and re-run."
}

# --- locate pg_dump ---
$pgDump = (Get-Command pg_dump -ErrorAction SilentlyContinue).Source
if (-not $pgDump) {
    $pgDump = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $pgDump) { throw 'pg_dump.exe not found (looked on PATH and C:\Program Files\PostgreSQL\*\bin)' }

Log "backup start -> $dest"

$dbDir = Join-Path $dest 'db'
foreach ($d in @($dest, $dbDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# --- pg_dump (custom format) ---
$stamp    = Get-Date -Format 'yyyyMMdd-HHmmss'
$dumpFile = Join-Path $dbDir "f7five0-$stamp.dump"
$env:PGPASSWORD = $pgPass
try {
    & $pgDump --format=custom --no-owner --host=$pgHost --port=$pgPort `
        --username=$pgUser --dbname=$pgDb --file=$dumpFile
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed ($LASTEXITCODE)" }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
$sizeMB = [math]::Round((Get-Item $dumpFile).Length / 1MB, 1)
Log "pg_dump ok -> $dumpFile ($sizeMB MB)"

# --- art + metadata-cache mirror ---
# Sourced from the runtime config so a drive-letter change in .env is picked
# up here too, instead of being hardcoded.
function Get-EnvPath($key, $fallback) {
    $v = ([regex]::Match($envText, "(?m)^$key=(.*)$")).Groups[1].Value.Trim()
    if ([string]::IsNullOrWhiteSpace($v)) { $fallback } else { $v }
}
$dataRoot = Join-Path (Split-Path $EnvFile -Parent) 'data'
$artSrc  = Get-EnvPath 'ART_ROOT'           (Join-Path $dataRoot 'art')
$metaSrc = Get-EnvPath 'METADATA_CACHE_ROOT' (Join-Path $dataRoot 'metadata-cache')

foreach ($pair in @(
    @{ Src = $artSrc;  Dst = (Join-Path $dest 'art') },
    @{ Src = $metaSrc; Dst = (Join-Path $dest 'metadata-cache') }
)) {
    if (Test-Path $pair.Src) {
        # /MT parallelizes the copy. The art tree is thousands of small files
        # and single-threaded robocopy over SMB crawls (first run especially);
        # /MT:32 cuts that dramatically. /MIR still mirrors deletes.
        robocopy $pair.Src $pair.Dst /MIR /MT:32 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        # robocopy exit codes < 8 are success (0-7 = copied/extra/mismatch, not failure).
        if ($LASTEXITCODE -ge 8) { throw "robocopy $($pair.Src) failed ($LASTEXITCODE)" }
        Log "mirrored $($pair.Src) -> $($pair.Dst)"
    } else {
        Log "WARN source missing, skipped: $($pair.Src)"
    }
}

# --- retention: prune old dumps ---
$cutoff = (Get-Date).AddDays(-$RetentionDays)
$pruned = 0
Get-ChildItem $dbDir -Filter '*.dump' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Remove-Item $_.FullName -Force; $pruned++ }
Log "retention: pruned $pruned dump(s) older than $RetentionDays days"

Log "backup complete"

# robocopy exits 1-7 on success (files copied, extras, etc.); that non-zero
# would otherwise become the script's exit code and make Task Scheduler report
# the nightly run as failed. We reached here without throwing, so report success.
exit 0
