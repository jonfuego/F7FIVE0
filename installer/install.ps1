<#
.SYNOPSIS
  Installs or upgrades F7FIVE0 on this Windows machine.

.DESCRIPTION
  One script does the whole job and is safe to re-run:

    1. Installs what F7FIVE0 needs: Python 3.12, PostgreSQL 16, Node.js,
       ffmpeg, and NSSM (the Windows service wrapper). Anything already
       present is reused.
    2. Copies the app into the install folder (default C:\F7FIVE0).
    3. Creates the database and writes .env with freshly generated secrets.
    4. Installs the backend packages and applies database migrations.
    5. Creates your admin account.
    6. Registers three Windows services (F7FIVE0-API, F7FIVE0-Stream,
       F7FIVE0-Web) that start with Windows.
    7. Optionally opens the firewall for your home network.
    8. Registers the F7FIVE0-RemoteAccess scheduled task, which the web
       app's Admin > Remote access page uses to set up access from anywhere
       (Tailscale, Cloudflare, or port forwarding) after install.
    9. Registers the F7FIVE0-Update scheduled task (SYSTEM, on demand), which
       Admin > Updates uses to update the server from a GitHub release or an
       uploaded Setup, and records the installed version in version.json.

  The Setup wizard (F7FIVE0-Setup.exe) runs this script for you. You can
  also run it by hand from an elevated PowerShell:

    powershell -ExecutionPolicy Bypass -File .\installer\install.ps1

  and it asks for anything it needs.

  Upgrading: run the new Setup.exe (or this script from the new release), or
  use Admin > Updates, which runs the same Setup silently (installer\update.ps1).
  Your .env, database, art, and watch history are kept, and so are the Windows
  account the services run as and the settings in the web app (NAS sign-ins,
  the TMDB key). Silent runs get no answers from the wizard, so every answer
  is "keep what is there".

.PARAMETER InstallDir
  Where F7FIVE0 lives. Default C:\F7FIVE0.

.PARAMETER ConfigFile
  JSON answers file written by the Setup wizard. Deleted after it is read.

.PARAMETER NonInteractive
  Never prompt. Missing answers fall back to defaults or fail.

.PARAMETER WebPort
  The one port people connect to. Default 3001. Setup stops if another
  program is already listening on it.

.PARAMETER ApiPort
  Internal API port on 127.0.0.1. Default 8001. When left unset and 8001 is
  taken, setup picks the next free port (8101, 8201, ...).

.PARAMETER RemoteAccess
  Advanced / recovery: set up remote access from this console as part of
  the install (tailscale, cloudflare, portforward, token, or none). Most
  people use Admin > Remote access in the web app instead. Same as running
  installer\remote-access.ps1 -Method <name> afterwards.

.PARAMETER StreamPort
  Internal stream gateway port on 127.0.0.1. Default 8002, same rules as
  ApiPort. An upgrade keeps the ports saved in .env.

  Example, next to another media server that already uses 3001/8001/8002:

    .\installer\install.ps1 -WebPort 3101 -ApiPort 8101 -StreamPort 8102
#>
[CmdletBinding()]
param(
    [string] $InstallDir = "C:\F7FIVE0",
    [string] $ConfigFile = "",
    [switch] $NonInteractive,

    # Answers (all optional; the wizard passes them through -ConfigFile).
    [string] $AdminUser = "",
    [string] $MoviesDir = "",
    [string] $TvDir = "",
    [string] $MusicDir = "",
    [string] $MusicVideosDir = "",
    [int]    $WebPort = 0,
    [int]    $ApiPort = 0,
    [int]    $StreamPort = 0,
    [string] $OpenFirewall = "",
    [ValidateSet("", "none", "tailscale", "cloudflare", "portforward", "token")]
    [string] $RemoteAccess = "",
    [string] $PublicHost = "",
    [string] $DuckDnsToken = "",
    [string] $TunnelToken = "",
    [string] $TmdbKey = "",
    [string] $ContactEmail = "",
    [string] $ServiceUser = ""
)

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is 10x faster without the bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$PythonWingetId = "Python.Python.3.12"
$PostgresWingetId = "PostgreSQL.PostgreSQL.16"
$NssmWingetId  = "NSSM.NSSM"

$ServiceNames = @("F7FIVE0-API", "F7FIVE0-Stream", "F7FIVE0-Web")
$RemoteAccessTask = "F7FIVE0-RemoteAccess"
$UpdateTask = "F7FIVE0-Update"
$DefaultApiPort = 8001
$DefaultStreamPort = 8002
$DbName = "f7five0"
$DbUser = "f7five0"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
$script:StepNo = 0
function Step([string]$msg) {
    $script:StepNo++
    Write-Host ""
    Write-Host ("[{0}] {1}" -f $script:StepNo, $msg) -ForegroundColor Cyan
}
# Info / Ok / Warn / Fail, Download, Invoke-Winget, Set-PrivateAcl,
# Set-EnvKey, Install-Svc, and friends live in common.ps1 (shared with
# remote-access.ps1).
. (Join-Path $PSScriptRoot "common.ps1")
# A click in the Setup console must not pause the install (QuickEdit).
$null = Disable-ConsoleQuickEdit
# Every Warn during this run, repeated in the summary at the end.
$script:Warnings = New-Object System.Collections.Generic.List[string]

# Pinned downloads live in installer\downloads.manifest.psd1 (SEC-P0-2): exact
# version, immutable URL, and SHA-256 per file. Get-DownloadSpec (common.ps1)
# reads them; the Download helper verifies the hash. To bump a version, see
# "Refreshing a pinned download" in CLAUDE.md. cloudflared and Caddy are only
# downloaded by remote-access.ps1, so their specs are read there.
$NodeSpec    = Get-DownloadSpec "node"
$NodeVersion = $NodeSpec.Version
$FfmpegSpec  = Get-DownloadSpec "ffmpeg"

function Ask([string]$prompt, [string]$default = "") {
    if ($NonInteractive) { return $default }
    $suffix = if ($default) { " [$default]" } else { "" }
    $a = Read-Host "$prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim()
}
function AskSecret([string]$prompt) {
    if ($NonInteractive) { return "" }
    $s = Read-Host $prompt -AsSecureString
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}
function AskYesNo([string]$prompt, [bool]$default) {
    $d = if ($default) { "Y" } else { "N" }
    $a = Ask "$prompt (Y/N)" $d
    return $a.ToUpper().StartsWith("Y")
}

# Media folders: one per library, or several separated by ";". The server
# reads the same format from LIBRARY_ROOT_* (app/services/library_folders.py).
function Split-Folders([string]$raw) {
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($part in ($raw -split ';')) {
        $p = $part.Trim().Trim('"').Trim()
        if (-not $p) { continue }
        if ($p.Length -gt 3) { $p = $p.TrimEnd('\') }
        if (-not ($out | Where-Object { $_ -ieq $p })) { $out.Add($p) }
    }
    return ,$out.ToArray()
}
function Join-Folders([string]$raw) { return ((Split-Folders $raw) -join ';') }

function Read-EnvPort([string]$key, [int]$fallback) {
    $m = Select-String -Path $EnvFile -Pattern "^$key=(\d+)" -ErrorAction SilentlyContinue
    if ($m) { return [int]$m.Matches[0].Groups[1].Value }
    return $fallback
}

# Name and PID of the process listening on a TCP port, or "" when free.
# Retries briefly so a service that was just stopped can release the port.
function Get-PortOwner([int]$port) {
    for ($i = 0; $i -lt 5; $i++) {
        $conn = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        if ($conn.Count -eq 0) { return "" }
        Start-Sleep -Seconds 1
    }
    $procId = $conn[0].OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { "an unknown program" }
    return "$name (PID $procId)"
}

# First port at or after $start (stepping by 100) that is free and not in $avoid.
function Find-FreePort([int]$start, [int[]]$avoid) {
    for ($p = $start; $p -le 65535; $p += 100) {
        if ($avoid -contains $p) { continue }
        if (-not @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue).Count) {
            if ($p -ne $start) { Info "port $start is taken; using $p instead" }
            return $p
        }
    }
    Fail "No free port found starting at $start."
}

function New-Secret([int]$bytes = 48) {
    $buf = New-Object byte[] $bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
    # URL-safe base64, no padding: safe inside .env and connection strings.
    return ([Convert]::ToBase64String($buf)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
$cfg = @{}
if ($ConfigFile -and (Test-Path $ConfigFile)) {
    $json = Get-Content -Raw -Path $ConfigFile | ConvertFrom-Json
    foreach ($p in $json.PSObject.Properties) { $cfg[$p.Name] = [string]$p.Value }
    Remove-Item -Force $ConfigFile -ErrorAction SilentlyContinue
    $NonInteractive = $true
}
function Answer([string]$name, [string]$current) {
    if ($current) { return $current }
    if ($cfg.ContainsKey($name)) { return $cfg[$name] }
    return ""
}
$AdminUser      = Answer "adminUser" $AdminUser
$AdminPassword  = Answer "adminPassword" ""
$MoviesDir      = Answer "moviesDir" $MoviesDir
$TvDir          = Answer "tvDir" $TvDir
$MusicDir       = Answer "musicDir" $MusicDir
$MusicVideosDir = Answer "musicVideosDir" $MusicVideosDir
$OpenFirewall   = Answer "openFirewall" $OpenFirewall
$TunnelToken    = Answer "tunnelToken" $TunnelToken
$RemoteAccess   = Answer "remoteAccess" $RemoteAccess
$PublicHost     = Answer "publicHost" $PublicHost
$DuckDnsToken   = Answer "duckDnsToken" $DuckDnsToken
$TmdbKey        = Answer "tmdbKey" $TmdbKey
$ContactEmail   = Answer "contactEmail" $ContactEmail
$ServiceUser    = Answer "serviceUser" $ServiceUser
$AppVersion     = Answer "appVersion" ""
$ServicePassword = Answer "servicePassword" ""
$PgSuperPassword = Answer "postgresPassword" ""
if (-not $WebPort) { $p = Answer "webPort" ""; $WebPort = if ($p) { [int]$p } else { 0 } }
if (-not $ApiPort) { $p = Answer "apiPort" ""; $ApiPort = if ($p) { [int]$p } else { 0 } }
if (-not $StreamPort) { $p = Answer "streamPort" ""; $StreamPort = if ($p) { [int]$p } else { 0 } }
# Ports given explicitly (parameter, wizard, or saved .env) are never moved;
# setup stops if one is taken. Unset internal ports may be moved to a free one.
$ApiPortPinned = [bool]$ApiPort
$StreamPortPinned = [bool]$StreamPort

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$BinDir     = Join-Path $InstallDir "bin"
$RuntimeDir = Join-Path $InstallDir "runtime"
$DataDir    = Join-Path $InstallDir "data"
$LogsDir    = Join-Path $InstallDir "logs"
$EnvFile    = Join-Path $InstallDir ".env"
$BackendDir = Join-Path $InstallDir "backend"
$WebDir     = Join-Path $InstallDir "web"
$VenvPy     = Join-Path $BackendDir ".venv\Scripts\python.exe"
$IsUpgrade  = Test-Path $EnvFile

foreach ($d in @($InstallDir, $BinDir, $RuntimeDir, $DataDir, $LogsDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}
$LogFile = Join-Path $LogsDir ("install-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
try { Start-Transcript -Path $LogFile -Append | Out-Null } catch { }

Write-Host ""
Write-Host "  F7FIVE0 setup" -ForegroundColor White
Write-Host "  Install folder: $InstallDir" -ForegroundColor Gray
if ($IsUpgrade) { Write-Host "  Existing install found: upgrading in place." -ForegroundColor Gray }

try {

# ---------------------------------------------------------------------------
Step "Securing the install folder"
# ---------------------------------------------------------------------------
$svcSid = $null
$script:KeepServiceAccount = $false
if ($ServiceUser) {
    $svcSid = Get-AccountSid $ServiceUser
    if (-not $svcSid) { Fail "Could not find the Windows account '$ServiceUser' (-ServiceUser)." }
} elseif ($IsUpgrade) {
    # An upgrade without -ServiceUser (the wizard never has it, and a silent
    # update can't ask for a password) keeps the Windows account the services
    # already run as: its folder rights stay, and Install-Svc changes the
    # services in place instead of re-creating them as LocalSystem.
    $svcSid = Get-ServiceAccountSid
    if ($svcSid) { $script:KeepServiceAccount = $true; Info "keeping the Windows account the services run as" }
}
Set-InstallAcl $InstallDir $svcSid
Ok "only administrators can change F7FIVE0's files"
# Let Users read Setup's own install log without elevation. Set-InstallAcl just
# reset the logs folder, so grant the log file now (and again at the end once
# the transcript has flushed). Service logs are not touched, so they stay
# private.
Grant-SetupLogRead $LogFile

# ---------------------------------------------------------------------------
Step "Checking this PC"
# ---------------------------------------------------------------------------
if (-not [Environment]::Is64BitOperatingSystem) { Fail "F7FIVE0 needs 64-bit Windows." }
$os = Get-CimInstance Win32_OperatingSystem
Info "$($os.Caption) ($($os.Version))"
$gpu = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "NVIDIA" })
$HasNvidia = $gpu.Count -gt 0
if ($HasNvidia) { Ok "NVIDIA GPU found ($($gpu[0].Name)): hardware transcoding on." }
else { Info "No NVIDIA GPU found: software transcoding (works fine for a few streams)." }

# ---------------------------------------------------------------------------
Step "Collecting settings"
# ---------------------------------------------------------------------------
if (-not $IsUpgrade) {
    if (-not $AdminUser) { $AdminUser = Ask "Admin username" "admin" }
    $AdminUser = $AdminUser.Trim().ToLower()
    if ($AdminUser -notmatch '^[a-z0-9._-]{3,64}$') { Fail "Admin username must be 3-64 characters: lowercase letters, digits, dot, dash, underscore." }
    while (-not $AdminPassword) {
        $p1 = AskSecret "Admin password (8+ characters)"
        $p2 = AskSecret "Confirm password"
        if ($NonInteractive) { break }
        if ($p1 -ne $p2) { Warn "Passwords do not match."; continue }
        if ($p1.Length -lt 8) { Warn "Too short."; continue }
        $AdminPassword = $p1
    }
    if (-not $AdminPassword -or $AdminPassword.Length -lt 8) { Fail "An admin password of 8+ characters is required." }

    if (-not ($MoviesDir -or $TvDir -or $MusicDir -or $MusicVideosDir) -and -not $NonInteractive) {
        Info "Point F7FIVE0 at your media folders. Leave any blank to skip it."
        Info "For more than one folder per library, separate them with ;  (D:\Movies; \\nas\media\Movies)"
        $MoviesDir = Ask "Movies folder(s)" ""
        $TvDir = Ask "TV shows folder(s)" ""
        $MusicDir = Ask "Music folder(s)" ""
        $MusicVideosDir = Ask "Music videos folder(s)" ""
    }
    $MoviesDir = Join-Folders $MoviesDir
    $TvDir = Join-Folders $TvDir
    $MusicDir = Join-Folders $MusicDir
    $MusicVideosDir = Join-Folders $MusicVideosDir
    if (-not $WebPort) { $WebPort = [int](Ask "Web port" "3001") }
    if (-not $OpenFirewall) { $OpenFirewall = if (AskYesNo "Allow phones, TVs, and other PCs on your home network to connect?" $true) { "1" } else { "0" } }
    $allFolders = @()
    foreach ($v in @($MoviesDir, $TvDir, $MusicDir, $MusicVideosDir)) { $allFolders += Split-Folders $v }
    foreach ($d in $allFolders) {
        if (-not (Test-Path -LiteralPath $d)) { Warn "Folder not found right now: $d (it will be scanned once it exists)." }
    }
} else {
    if (-not $WebPort) { $WebPort = Read-EnvPort "WEB_PORT" 3001 }
    if (-not $ApiPort) { $ApiPort = Read-EnvPort "API_PORT" 0; $ApiPortPinned = [bool]$ApiPort }
    if (-not $StreamPort) { $StreamPort = Read-EnvPort "STREAM_PORT" 0; $StreamPortPinned = [bool]$StreamPort }
}
if (-not $WebPort) { $WebPort = 3001 }
if (-not $ApiPort) { $ApiPort = $DefaultApiPort }
if (-not $StreamPort) { $StreamPort = $DefaultStreamPort }
if ($ServiceUser -and -not $ServicePassword) {
    $ServicePassword = AskSecret "Windows password for $ServiceUser (services run as this account)"
    if (-not $ServicePassword) { Fail "A password for $ServiceUser is required to run the services as that account." }
}

# ---------------------------------------------------------------------------
Step "Stopping F7FIVE0 services (if running)"
# ---------------------------------------------------------------------------
foreach ($svc in $ServiceNames) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s -and $s.Status -ne "Stopped") { Info "stop $svc"; Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------------------
Step "Checking ports"
# ---------------------------------------------------------------------------
# F7FIVE0's own services are stopped above, so anything still listening on
# these ports belongs to another program (for example another media server).
foreach ($pair in @(@("Web", $WebPort), @("API", $ApiPort), @("Stream", $StreamPort))) {
    if ($pair[1] -lt 1024 -or $pair[1] -gt 65535) { Fail "$($pair[0]) port $($pair[1]) is out of range (1024-65535)." }
}
if (-not $ApiPortPinned) { $ApiPort = Find-FreePort $ApiPort @($WebPort) }
if (-not $StreamPortPinned) { $StreamPort = Find-FreePort $StreamPort @($WebPort, $ApiPort) }
if (($WebPort -eq $ApiPort) -or ($WebPort -eq $StreamPort) -or ($ApiPort -eq $StreamPort)) {
    Fail "Web ($WebPort), API ($ApiPort), and stream ($StreamPort) ports must all be different."
}
foreach ($pair in @(@("Web", $WebPort, "-WebPort"), @("API", $ApiPort, "-ApiPort"), @("Stream", $StreamPort, "-StreamPort"))) {
    $owner = Get-PortOwner $pair[1]
    if ($owner) {
        Fail "$($pair[0]) port $($pair[1]) is already in use by $owner. Stop that program or run setup with a different port, for example $($pair[2]) $([int]$pair[1] + 100)."
    }
}
Ok "ports: web $WebPort, API $ApiPort, stream $StreamPort"

# ---------------------------------------------------------------------------
Step "Installing prerequisites"
# ---------------------------------------------------------------------------
# Python (machine-wide, so services running as any account can use it).
function Find-Python {
    $cands = @()
    $reg = Get-ItemProperty "HKLM:\SOFTWARE\Python\PythonCore\3.1[2-4]\InstallPath" -ErrorAction SilentlyContinue
    foreach ($r in @($reg)) { if ($r -and $r.ExecutablePath) { $cands += $r.ExecutablePath } }
    $cands += "$env:ProgramFiles\Python312\python.exe", "$env:ProgramFiles\Python313\python.exe", "$env:ProgramFiles\Python314\python.exe"
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}
$Py = Find-Python
if (-not $Py) {
    Invoke-Winget $PythonWingetId @("--scope", "machine")
    $Py = Find-Python
}
if (-not $Py) { Fail "Python 3.12 did not install. Install it from python.org (All users), then run Setup again." }
Ok "Python: $Py"

# Node.js: private copy under runtime\ so it never clashes with a system Node.
$NodeDir = Join-Path $RuntimeDir "node"
$Node = Join-Path $NodeDir "node.exe"
$nodeOk = (Test-Path $Node) -and ((& $Node --version) -eq "v$NodeVersion")
if (-not $nodeOk) {
    $zip = Join-Path $env:TEMP "f7five0-node.zip"
    Download $NodeSpec.Url $zip $NodeSpec.Sha256 $NodeSpec.Publisher
    $unz = Join-Path $env:TEMP "f7five0-node"
    if (Test-Path $unz) { Remove-Item -Recurse -Force $unz }
    Expand-Archive -Path $zip -DestinationPath $unz -Force
    if (Test-Path $NodeDir) { Remove-Item -Recurse -Force $NodeDir }
    Move-Item (Get-ChildItem $unz | Select-Object -First 1).FullName $NodeDir
    Remove-Item -Force $zip
}
Ok "Node.js: $Node"

# ffmpeg + ffprobe into bin\.
$Ffmpeg = Join-Path $BinDir "ffmpeg.exe"
$Ffprobe = Join-Path $BinDir "ffprobe.exe"
if (-not ((Test-Path $Ffmpeg) -and (Test-Path $Ffprobe))) {
    $zip = Join-Path $env:TEMP "f7five0-ffmpeg.zip"
    Download $FfmpegSpec.Url $zip $FfmpegSpec.Sha256 $FfmpegSpec.Publisher
    $unz = Join-Path $env:TEMP "f7five0-ffmpeg"
    if (Test-Path $unz) { Remove-Item -Recurse -Force $unz }
    Expand-Archive -Path $zip -DestinationPath $unz -Force
    $bin = Get-ChildItem -Path $unz -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    Copy-Item $bin.FullName $Ffmpeg -Force
    Copy-Item (Join-Path $bin.DirectoryName "ffprobe.exe") $Ffprobe -Force
    Remove-Item -Recurse -Force $unz, $zip
}
Ok "ffmpeg: $Ffmpeg"

# NSSM into bin\.
$Nssm = Join-Path $BinDir "nssm.exe"
if (-not (Test-Path $Nssm)) {
    $found = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $found) { Invoke-Winget $NssmWingetId; $found = Get-Command nssm -ErrorAction SilentlyContinue }
    $src = if ($found) { $found.Source } else { $null }
    if (-not $src) {
        $src = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages", "$env:ProgramFiles\WinGet\Packages" -Recurse -Filter nssm.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "win64" } | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $src) { Fail "NSSM did not install. Download nssm.exe (64-bit) from nssm.cc into $BinDir and run Setup again." }
    Copy-Item $src $Nssm -Force
}
Ok "NSSM: $Nssm"

# PostgreSQL.
function Find-Psql {
    $roots = @(Get-ChildItem "$env:ProgramFiles\PostgreSQL" -Directory -ErrorAction SilentlyContinue | Sort-Object { [int]($_.Name -replace '\D', '0') } -Descending)
    foreach ($r in $roots) { $p = Join-Path $r.FullName "bin\psql.exe"; if (Test-Path $p) { return $p } }
    $c = Get-Command psql -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

# After an uninstall, PostgreSQL can leave its service entry, the "postgres"
# Windows account and its data folder behind (see the PostgreSQL leftovers
# section of common.ps1). Called only when no usable PostgreSQL exists. Returns
# the password to hand the PostgreSQL installer for the postgres account when a
# leftover account had to be reset, else "". Nothing that holds data is deleted:
# a service entry whose program is gone is removed, the account's password is
# reset, an old data folder is renamed aside. Never fatal.
function Clear-PostgresLeftovers {
    $svcPassword = ""
    try {
        $all = @(Get-CimInstance Win32_Service -ErrorAction Stop)
    } catch {
        Warn "could not list the Windows services to look for PostgreSQL leftovers: $($_.Exception.Message)"
        return ""
    }
    # 1. A service entry whose program is gone would stop the installer from
    #    creating a service of the same name.
    foreach ($svc in @(Find-OrphanPgServices $all)) {
        Info "found a leftover service entry '$($svc.Name)' from a PostgreSQL that was uninstalled; removing the entry"
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
            & sc.exe delete $svc.Name | Out-Null
            if ($LASTEXITCODE -ne 0) { Warn "sc.exe delete $($svc.Name) returned $LASTEXITCODE" }
        } finally { $ErrorActionPreference = $prev }
    }
    # 2. An old data folder: a new PostgreSQL must not meet a cluster it did not make.
    foreach ($oldData in @(Find-PgLeftoverDataDirs (Join-Path $env:ProgramFiles "PostgreSQL"))) {
        try {
            $to = Move-PgDataAside $oldData (Get-Date -Format "yyyyMMdd-HHmmss")
            Warn "an old PostgreSQL data folder was left behind. Moved it to $to (nothing was deleted); copy it back if you still need it."
        } catch {
            Warn "could not move the old PostgreSQL data folder $oldData aside ($($_.Exception.Message)). The PostgreSQL install may fail; rename that folder and run Setup again."
        }
    }
    # 3. The "postgres" Windows account. The installer wants its password, and
    #    by default offers the new superuser password, which will not match.
    try {
        $acct = Get-LocalUser -Name "postgres" -ErrorAction SilentlyContinue
        if ($acct) {
            if (Test-PgAccountOrphan $all "postgres") {
                $newPassword = New-Secret 24
                $note = Join-Path $DataDir "postgres-service-account.txt"
                # Save the password BEFORE resetting the account, like the superuser one.
                Set-Content -Path $note -Value "Windows account 'postgres' (runs the PostgreSQL service). F7FIVE0 setup reset its password because an old one was left behind:`r`n$newPassword" -Encoding ASCII
                Set-PrivateAcl $note
                Set-LocalUser -Name "postgres" -Password (ConvertTo-SecureString $newPassword -AsPlainText -Force)
                if (-not $acct.Enabled) { Enable-LocalUser -Name "postgres" }
                $svcPassword = $newPassword
                Info "found the 'postgres' Windows account from an earlier PostgreSQL; reset its password so the new PostgreSQL can use it (saved in $note)"
            } else {
                Info "the 'postgres' Windows account is still used by a PostgreSQL service that exists; leaving it alone"
            }
        }
    } catch {
        $svcPassword = ""
        Warn "could not reset the leftover 'postgres' Windows account ($($_.Exception.Message)). The PostgreSQL install may fail; see INSTALL.md, 'Already have PostgreSQL?'."
    }
    return $svcPassword
}

$Psql = Find-Psql
$PgInstalledNow = $false
if (-not $Psql -and -not $IsUpgrade) {
    if (-not $PgSuperPassword) { $PgSuperPassword = New-Secret 24 }
    # Save the password BEFORE installing: winget can report failure for an
    # install that worked, and a lost password means a manual reset.
    $pgNote = Join-Path $DataDir "postgres-superuser.txt"
    Set-Content -Path $pgNote -Value "PostgreSQL superuser 'postgres' password (created by F7FIVE0 setup):`r`n$PgSuperPassword" -Encoding ASCII
    Set-PrivateAcl $pgNote
    Info "installing PostgreSQL 16. This is the slow one: usually 5-10 minutes with nothing on screen."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "winget is not available. Install 'App Installer' from the Microsoft Store, then run Setup again."
    }
    # A PostgreSQL that was uninstalled can leave its service entry, the postgres
    # Windows account and its data behind; clear them so the new install works.
    $pgSvcPassword = @(Clear-PostgresLeftovers) | Select-Object -Last 1
    $pgOverride = "--mode unattended --unattendedmodeui none --superpassword \`"$PgSuperPassword\`" --serverport 5432 --enable-components server,commandlinetools"
    if ($pgSvcPassword) { $pgOverride += " --serviceaccount postgres --servicepassword \`"$pgSvcPassword\`"" }
    $pgArgs = "install --id $PostgresWingetId -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --override `"$pgOverride`""
    $pgStart = Get-Date
    $pgProc = Start-Process -FilePath "winget" -ArgumentList $pgArgs -NoNewWindow -PassThru
    $null = $pgProc.Handle
    $nextBeat = 30
    while (-not $pgProc.WaitForExit(1000)) {
        $elapsed = [int]((Get-Date) - $pgStart).TotalSeconds
        if ($elapsed -ge $nextBeat) {
            $svcNote = if (Get-Service -Name "postgresql-x64-16" -ErrorAction SilentlyContinue) { ", database service registered" } else { "" }
            Info ("still installing PostgreSQL ({0}:{1:00} elapsed{2})" -f [int][math]::Floor($elapsed / 60), ($elapsed % 60), $svcNote)
            $nextBeat += 30
        }
    }
    $pgRc = $pgProc.ExitCode
    Refresh-Path
    # Judge by the result on disk, not winget's exit code (it has reported
    # 0x80004004 "abandoned" for an install that completed).
    $pgSvc = $null
    for ($i = 0; $i -lt 30; $i++) {
        $Psql = Find-Psql
        $pgSvc = Get-Service -Name "postgresql-x64-16" -ErrorAction SilentlyContinue
        if ($Psql -and $pgSvc -and $pgSvc.Status -eq "Running") { break }
        Start-Sleep -Seconds 2
    }
    if (-not ($Psql -and $pgSvc -and $pgSvc.Status -eq "Running")) {
        $edbLog = Join-Path $env:TEMP "install-postgresql.log"
        if (Test-Path $edbLog) {
            Warn "PostgreSQL installer log ($edbLog), last lines:"
            Get-Content $edbLog -Tail 25 | ForEach-Object { Info $_ }
        }
        Fail "PostgreSQL did not install (winget exit $pgRc). Install PostgreSQL 16 from postgresql.org, then run Setup again. The superuser password Setup chose is in $pgNote."
    }
    if ($pgRc -ne 0 -and $pgRc -ne -1978335189) { Info "winget reported exit $pgRc, but PostgreSQL is installed and running; carrying on." }
    $PgInstalledNow = $true
    Ok "PostgreSQL installed. Superuser password saved to $pgNote (Administrators only)."
} elseif ($Psql) {
    Ok "PostgreSQL: $Psql"
}

# ---------------------------------------------------------------------------
Step "Copying F7FIVE0 into $InstallDir"
# ---------------------------------------------------------------------------
function Mirror([string]$from, [string]$to, [string[]]$excludeDirs = @()) {
    $xd = @()
    if ($excludeDirs.Count) { $xd = @("/XD") + $excludeDirs }
    & robocopy $from $to /MIR /NFL /NDL /NJH /NJS /NC /NS /NP @xd | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "copy $from -> $to failed (robocopy $LASTEXITCODE)" }
}
$sameDir = ([IO.Path]::GetFullPath($SourceDir).TrimEnd('\') -ieq $InstallDir.TrimEnd('\'))

# Web bundle: prebuilt in releases; built here when running from a git clone.
$srcWeb = Join-Path $SourceDir "web"
if (-not (Test-Path (Join-Path $srcWeb "server.js"))) {
    $frontend = Join-Path $SourceDir "frontend"
    if (-not (Test-Path (Join-Path $frontend "package.json"))) { Fail "No web bundle found in $SourceDir." }
    Info "building the web app (first run from source takes a few minutes)"
    $npm = Join-Path $NodeDir "npm.cmd"
    $env:Path = "$NodeDir;$env:Path"
    Push-Location $frontend
    try {
        & $npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Fail "npm ci failed ($LASTEXITCODE)" }
        & $npm run build
        if ($LASTEXITCODE -ne 0) { Fail "web build failed ($LASTEXITCODE)" }
    } finally { Pop-Location }
    $standalone = Join-Path $frontend ".next\standalone"
    Mirror (Join-Path $frontend ".next\static") (Join-Path $standalone ".next\static")
    Mirror (Join-Path $frontend "public") (Join-Path $standalone "public")
    # The launcher runs instead of server.js; lay it next to server.js.
    Copy-Item (Join-Path $frontend "server-wrapper.js") (Join-Path $standalone "server-wrapper.js") -Force
    $srcWeb = $standalone
}
if (-not $sameDir -or $srcWeb -ne (Join-Path $InstallDir "web")) {
    Mirror $srcWeb $WebDir
}
if (-not $sameDir) {
    Mirror (Join-Path $SourceDir "backend") $BackendDir @(".venv", "__pycache__", ".pytest_cache", "tests")
    Mirror (Join-Path $SourceDir "installer") (Join-Path $InstallDir "installer")
    $srcScripts = Join-Path $SourceDir "scripts"
    if (Test-Path $srcScripts) { Mirror $srcScripts (Join-Path $InstallDir "scripts") }
    foreach ($f in @("alembic.ini", ".env.example", "LICENSE", "README.md", "INSTALL.md", "VERSION")) {
        $s = Join-Path $SourceDir $f
        if (Test-Path $s) { Copy-Item $s (Join-Path $InstallDir $f) -Force }
    }
}
foreach ($d in @("art", "metadata-cache", "transcode-cache", "downloads")) {
    $p = Join-Path $DataDir $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}
Ok "files in place"

# Android app. Releases bundle the phone APK that matches this version in
# android\ (installer\build-dist.ps1). Copy the newest one per ABI into
# data\downloads, where the web app stamps it with this server's addresses on
# every download, and drop the phone APKs it replaces so the server and the
# app it hands out stay on the same version. TV builds are left alone. Never
# fatal: without an APK the server simply does not offer the app.
$AndroidAppVersion = ""
$apkSrc = Join-Path $SourceDir "android"
$apkDest = Join-Path $DataDir "downloads"
$apkPattern = '^F7FIVE0-(\d+\.\d+\.\d+)(-armv7)?\.apk$'
$bundled = @{}
if (Test-Path $apkSrc) {
    foreach ($f in Get-ChildItem $apkSrc -Filter "F7FIVE0-*.apk" -File) {
        if ($f.Name -notmatch $apkPattern) { continue }
        $ver = [version]$matches[1]
        $abiKey = if ($matches[2]) { "armv7" } else { "arm64" }
        if (-not $bundled.ContainsKey($abiKey) -or $ver -gt $bundled[$abiKey].Version) {
            $bundled[$abiKey] = @{ File = $f; Version = $ver }
        }
    }
}
if ($bundled.Count -eq 0) {
    Info "no Android app in this package; the server will not offer one"
} else {
    $keep = @()
    foreach ($abiKey in @($bundled.Keys)) {
        $f = $bundled[$abiKey].File
        $shaFile = "$($f.FullName).sha256"
        try {
            if (-not (Test-Path $shaFile)) { throw "no .sha256 file" }
            $want = ((Get-Content $shaFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
            $got = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($want -ne $got) { throw "checksum mismatch" }
            $target = Join-Path $apkDest $f.Name
            if ($f.FullName -ne $target) { Copy-Item $f.FullName $target -Force }
            $keep += $f.Name
            if ($abiKey -eq "arm64") { $AndroidAppVersion = "$($bundled[$abiKey].Version)" }
        } catch {
            Warn "Android app $($f.Name) not published: $($_.Exception.Message)"
        }
    }
    if ($keep.Count) {
        foreach ($old in Get-ChildItem $apkDest -Filter "F7FIVE0-*.apk" -File) {
            if ($old.Name -match $apkPattern -and $keep -notcontains $old.Name) {
                Remove-Item $old.FullName -Force -ErrorAction SilentlyContinue
                Info "removed old Android app $($old.Name)"
            }
        }
        Ok "Android app ready: $($keep -join ', ')"
    }
}

# ---------------------------------------------------------------------------
Step "Database"
# ---------------------------------------------------------------------------
$DbPassword = $null
if (-not $IsUpgrade) {
    # A rerun after a failed first install reuses the password Setup saved
    # itself (the wizard skips its password page when this file exists).
    $saved = Join-Path $DataDir "postgres-superuser.txt"
    if (-not $PgSuperPassword) {
        if (Test-Path $saved) { $PgSuperPassword = (Get-Content $saved | Select-Object -Last 1).Trim() }
    }
    if (-not $PgSuperPassword) {
        Info "PostgreSQL is already installed on this PC. F7FIVE0 needs its 'postgres' password once to create its own database."
        $PgSuperPassword = AskSecret "PostgreSQL 'postgres' password"
    }
    if (-not $PgSuperPassword) { Fail "The PostgreSQL 'postgres' password is required on first install." }
    $env:PGPASSWORD = $PgSuperPassword
    # Windows PowerShell turns native stderr into terminating errors under
    # "Stop", so psql runs with Continue and we check its exit code instead.
    function Psql([string]$sql) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $out = & $Psql -h 127.0.0.1 -U postgres -d postgres -tA -v ON_ERROR_STOP=1 -c $sql 2>&1
            $script:PsqlExit = $LASTEXITCODE
            return ("$out").Trim()
        } finally { $ErrorActionPreference = $prev }
    }
    $DbPassword = New-Secret 24
    $ready = $false
    $lastErr = ""
    for ($i = 0; $i -lt 30; $i++) {
        $lastErr = Psql "SELECT 1"
        if ($script:PsqlExit -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { Fail "Could not sign in to PostgreSQL as 'postgres' on 127.0.0.1:5432 ($lastErr). Check the password and that the PostgreSQL service is running. If Setup reused the password saved in postgres-superuser.txt ($saved) and PostgreSQL has a different one, correct or delete that file and run Setup again; see INSTALL.md, 'Already have PostgreSQL?'." }
    $verb = if ((Psql "SELECT 1 FROM pg_roles WHERE rolname='$DbUser'") -eq "1") { "ALTER" } else { "CREATE" }
    $r = Psql "$verb ROLE $DbUser WITH LOGIN PASSWORD '$DbPassword';"
    if ($script:PsqlExit -ne 0) { Fail "Could not create the database role: $r" }
    if ((Psql "SELECT 1 FROM pg_database WHERE datname='$DbName'") -ne "1") {
        $r = Psql "CREATE DATABASE $DbName OWNER $DbUser ENCODING 'UTF8' TEMPLATE template0;"
        if ($script:PsqlExit -ne 0) { Fail "Could not create the database: $r" }
    }
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    Ok "database '$DbName' ready"
} else {
    Ok "keeping the existing database"
}

# ---------------------------------------------------------------------------
Step "Writing configuration (.env)"
# ---------------------------------------------------------------------------
# Existing keys always win, so an upgrade never clobbers your settings
# (Merge-EnvFile in common.ps1; installer\tests\update-verify.ps1 covers it).
$want = [ordered]@{
    "ENVIRONMENT"             = "production"
    "LOG_LEVEL"               = "INFO"
    "DATABASE_URL"            = if ($DbPassword) { "postgresql+psycopg://${DbUser}:$DbPassword@127.0.0.1:5432/$DbName" } else { "" }
    "JWT_SECRET"              = New-Secret 64
    "STREAM_HMAC_SECRET"      = New-Secret 64
    "FFMPEG_BIN"              = $Ffmpeg
    "FFPROBE_BIN"             = $Ffprobe
    "NVENC_ENABLED"           = if ($HasNvidia) { "true" } else { "false" }
    "TRANSCODE_CACHE_DIR"     = Join-Path $DataDir "transcode-cache"
    "ART_ROOT"                = Join-Path $DataDir "art"
    "METADATA_CACHE_ROOT"     = Join-Path $DataDir "metadata-cache"
    "LIBRARY_ROOT_MOVIES"     = $MoviesDir
    "LIBRARY_ROOT_TV"         = $TvDir
    "LIBRARY_ROOT_MUSIC"      = $MusicDir
    "LIBRARY_ROOT_MUSIC_VIDEOS" = $MusicVideosDir
    "TMDB_API_KEY"            = $TmdbKey
    "MUSICBRAINZ_USER_AGENT_EMAIL" = $ContactEmail
    "API_PORT"                = "$ApiPort"
    "STREAM_PORT"             = "$StreamPort"
    "WEB_PORT"                = "$WebPort"
    "F7FIVE0_DOWNLOADS_DIR"   = Join-Path $DataDir "downloads"
    # SEC-P1-1: only the local front door may set forwarding headers. The Next
    # proxy and any tunnel run on this host over loopback, so loopback is the
    # whole trusted set for a normal install. Add a LAN proxy IP/CIDR here only
    # if one actually fronts the services.
    "TRUSTED_PROXIES"         = "127.0.0.1,::1"
    # Shared secret the Caddy front door sends to the Next web app as the
    # X-F7five0-Proxy header so Next forwards the real client-IP headers to the
    # backend only on that trusted path; a direct LAN browser can't spoof an IP.
    # remote-access.ps1 reads this back and writes header_up into the Caddyfile.
    "TRUSTED_PROXY_SECRET"    = New-Secret 48
}
# Ports are the exception: the services are registered with the ports chosen
# above, so .env must match them even when they changed on this run.
$portKeys = @{ "API_PORT" = "$ApiPort"; "STREAM_PORT" = "$StreamPort"; "WEB_PORT" = "$WebPort" }
$added = Merge-EnvFile $EnvFile $want $portKeys
# The services read .env, so their account (when not SYSTEM) gets read access.
Set-PrivateAcl $EnvFile @($svcSid)
Ok ("{0} ({1} new setting(s))" -f $EnvFile, $added)

# ---------------------------------------------------------------------------
Step "Backend packages"
# ---------------------------------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    & $Py -m venv (Join-Path $BackendDir ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "could not create the Python virtual environment" }
}
& $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip
# Install the hash-pinned lock (SEC-P0-1): --require-hashes refuses any dist
# whose SHA-256 is not pinned, so a swapped or tampered wheel fails the
# install rather than running with SYSTEM/service authority.
# Run pip in its own process with a heartbeat like PostgreSQL's, so a slow
# download never looks like a hang. --timeout/--retries make a dead
# connection end in an error; the hard cap stops anything else that sticks.
# pip's own output goes to logs\pip-install-*.log (shown here on failure).
$pipStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$pipOut = Join-Path $LogsDir "pip-install-$pipStamp.log"
$pipErr = Join-Path $LogsDir "pip-install-$pipStamp.err.log"
$pipLock = Join-Path $BackendDir "requirements.lock"
$pipArgs = "-m pip install --disable-pip-version-check --no-input --progress-bar off --timeout 60 --retries 5 --require-hashes -r `"$pipLock`""
$pipMaxSeconds = 45 * 60
$pipStart = Get-Date
$pipProc = Start-Process -FilePath $VenvPy -ArgumentList $pipArgs -NoNewWindow -PassThru -RedirectStandardOutput $pipOut -RedirectStandardError $pipErr
$null = $pipProc.Handle
$nextBeat = 30
while (-not $pipProc.WaitForExit(1000)) {
    $elapsed = [int]((Get-Date) - $pipStart).TotalSeconds
    if ($elapsed -ge $pipMaxSeconds) {
        try { $pipProc.Kill() } catch { }
        Fail "Python packages did not finish installing in $([int]($pipMaxSeconds / 60)) minutes. Check the internet connection, then run Setup again. pip's output is in $pipOut."
    }
    if ($elapsed -ge $nextBeat) {
        Info ("still installing Python packages ({0}:{1:00} elapsed)" -f [int][math]::Floor($elapsed / 60), ($elapsed % 60))
        $nextBeat += 30
    }
}
$pipRc = $pipProc.ExitCode
if ($pipRc -ne 0) {
    foreach ($f in @($pipErr, $pipOut)) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) {
            Warn "pip output ($f), last lines:"
            Get-Content $f -Tail 25 | ForEach-Object { Info $_ }
        }
    }
    Fail "pip install failed ($pipRc). Full output: $pipOut"
}
# Compile now: a -ServiceUser account can't write __pycache__ in backend\.
& $VenvPy -m compileall -q (Join-Path $BackendDir "app") | Out-Null
Ok "Python packages installed"

# ---------------------------------------------------------------------------
Step "Database migrations"
# ---------------------------------------------------------------------------
$env:PYTHONPATH = $BackendDir
Push-Location $InstallDir
try {
    & $VenvPy -m alembic -c (Join-Path $InstallDir "alembic.ini") upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "alembic upgrade failed ($LASTEXITCODE)" }
} finally { Pop-Location }
Ok "schema up to date"

if (-not $IsUpgrade -and $AdminUser) {
    Step "Creating admin account '$AdminUser'"
    $env:F7FIVE0_ADMIN_PASSWORD = $AdminPassword
    Push-Location $BackendDir
    try {
        & $VenvPy -m app.cli create-admin --username $AdminUser --name $AdminUser
        $rc = $LASTEXITCODE
    } finally {
        Pop-Location
        Remove-Item Env:\F7FIVE0_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    }
    if ($rc -eq 1) { Warn "user '$AdminUser' already exists; keeping it." }
    elseif ($rc -ne 0) { Fail "could not create the admin account ($rc)" }
    else { Ok "admin created" }
}

# ---------------------------------------------------------------------------
Step "Windows services"
# ---------------------------------------------------------------------------
$pyEnv = @("PYTHONPATH=$BackendDir", "PYTHONUNBUFFERED=1", "PYTHONIOENCODING=utf-8")
Install-Svc "F7FIVE0-API" $VenvPy "-m uvicorn app.main:app --host 127.0.0.1 --port $ApiPort --proxy-headers" $BackendDir $pyEnv "F7FIVE0 API"
# Single worker on purpose: the transcoder session registry is in-process.
Install-Svc "F7FIVE0-Stream" $VenvPy "-m uvicorn app.stream:app --host 127.0.0.1 --port $StreamPort --workers 1 --proxy-headers" $BackendDir $pyEnv "F7FIVE0 stream gateway"
# Listen on the network only when LAN access was chosen (or chosen on an
# earlier install). Tunnel-only installs stay on loopback.
$lanRule = Get-NetFirewallRule -DisplayName "F7FIVE0 web" -ErrorAction SilentlyContinue
$bind = if ($OpenFirewall -eq "1" -or $lanRule) { "0.0.0.0" } else { "127.0.0.1" }
# The Next proxy needs the trusted-proxy secret so it can tell front-door
# traffic (Caddy sends it as X-F7five0-Proxy) from a direct LAN browser and
# forward client-IP headers only on the trusted path. Read the effective value
# from .env (an existing one wins over the freshly generated one above).
$webEnv = @(
    "NODE_ENV=production", "PORT=$WebPort", "HOSTNAME=$bind",
    "API_ORIGIN=http://127.0.0.1:$ApiPort", "STREAM_ORIGIN=http://127.0.0.1:$StreamPort",
    "F7FIVE0_DOWNLOADS_DIR=$(Join-Path $DataDir 'downloads')",
    "TRUSTED_PROXY_SECRET=$(Get-EnvValue 'TRUSTED_PROXY_SECRET')",
    "NEXT_TELEMETRY_DISABLED=1"
)
# Run the launcher (server-wrapper.js), never server.js directly. The launcher
# stamps the real socket peer as x-f7five0-peer and sets F7FIVE0_LAUNCHER so the
# Next proxy can record the real client IP (criterion 4); it ships next to
# server.js via build-dist.ps1. Install-Svc removes and re-registers the service,
# so re-running Setup upgrades an existing install onto the launcher.
$webLauncher = Join-Path $WebDir 'server-wrapper.js'
if (-not (Test-Path $webLauncher)) { Fail "web launcher missing: $webLauncher" }
Install-Svc "F7FIVE0-Web" $Node "`"$webLauncher`"" $WebDir $webEnv "F7FIVE0 web app"

if ($OpenFirewall -eq "1" -or $lanRule) {
    if ($lanRule) {
        # Follow a changed WEB_PORT.
        $lanRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -LocalPort $WebPort
    } else {
        New-NetFirewallRule -DisplayName "F7FIVE0 web" -Direction Inbound -Protocol TCP -LocalPort $WebPort -Action Allow -Profile Private,Domain | Out-Null
    }
    Ok "firewall open on port $WebPort for private (home) networks"
}

# ---------------------------------------------------------------------------
Step "Remote access helper"
# ---------------------------------------------------------------------------
# Admin > Remote access in the web app sets up Tailscale, Cloudflare, or port
# forwarding after install, while the person is at the screen. The API may
# run as a non-admin account, so the privileged steps run in a scheduled task
# (SYSTEM, on demand only) that the API's account is allowed to start. See
# installer\remote-access.ps1.
$RaDir = Join-Path $DataDir "remote-access"
if (-not (Test-Path $RaDir)) { New-Item -ItemType Directory -Path $RaDir | Out-Null }
$raGrants = @("*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F")
if ($svcSid) { $raGrants += "*${svcSid}:(OI)(CI)M" }
# Requests can carry tokens: only admins, SYSTEM, and the service account.
# /reset first drops a previous service account's entry.
& icacls $RaDir /reset | Out-Null
& icacls $RaDir /inheritance:r /grant:r @raGrants | Out-Null
# The task runs installer\remote-access.ps1 as SYSTEM. The install folder ACL
# (Set-InstallAcl) already limits changes to administrators; this keeps the
# installer folder locked even if someone loosens the folder above it.
& icacls (Join-Path $InstallDir "installer") /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" | Out-Null
$raScript = Join-Path $InstallDir "installer\remote-access.ps1"
$raAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$raScript`" -InstallDir `"$InstallDir`" -FromRequest" -WorkingDirectory $InstallDir
$raPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$raSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $RemoteAccessTask -Action $raAction -Principal $raPrincipal -Settings $raSettings -Description "Runs F7FIVE0 remote access setup when an admin starts it from the web app." -Force | Out-Null
if ($svcSid) {
    # Read + execute on the task lets that account start it (schtasks /Run).
    $sched = New-Object -ComObject Schedule.Service
    $sched.Connect()
    $raTask = $sched.GetFolder("\").GetTask($RemoteAccessTask)
    $sddl = $raTask.GetSecurityDescriptor(4)   # DACL only
    if ($sddl -notmatch [regex]::Escape($svcSid)) { $raTask.SetSecurityDescriptor("$sddl(A;;GRGX;;;$svcSid)", 0) }
}
Ok "scheduled task $RemoteAccessTask registered (used by Admin > Remote access)"

# ---------------------------------------------------------------------------
Step "Updater"
# ---------------------------------------------------------------------------
# Admin > Updates updates the server from a GitHub release or an uploaded
# Setup. The web app verifies the Setup and writes a request; F7FIVE0-Update
# (a scheduled task that runs as SYSTEM, on demand only) runs the updater. The
# task runs a COPY of update.ps1 kept under data\updates\run, because Setup
# replaces the install folder while the updater is still running. See
# installer\update.ps1.
$UpdDir = Join-Path $DataDir "updates"
$UpdRun = Join-Path $UpdDir "run"
foreach ($d in @($UpdDir, (Join-Path $UpdDir "incoming"), (Join-Path $UpdDir "setup"), (Join-Path $UpdDir "backup"), $UpdRun)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}
# updates\ and incoming\: the web app's account writes the request, the status,
# and the Setup it downloaded. run\ holds the updater itself and backup\ holds
# full database dumps: Administrators and SYSTEM only. setup\ holds the cached
# Setups a rollback runs: Administrators and SYSTEM write, the service account
# may only read.
$upGrants = @("*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F")
if ($svcSid) { $upGrants += "*${svcSid}:(OI)(CI)M" }
& icacls $UpdDir /reset | Out-Null
& icacls $UpdDir /inheritance:r /grant:r @upGrants | Out-Null
foreach ($sub in @("run", "backup")) {
    & icacls (Join-Path $UpdDir $sub) /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
}
$setupGrants = @("*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F")
if ($svcSid) { $setupGrants += "*${svcSid}:(OI)(CI)RX" }
& icacls (Join-Path $UpdDir "setup") /inheritance:r /grant:r @setupGrants | Out-Null
foreach ($name in @("update.ps1", "common.ps1")) {
    $from = Join-Path $InstallDir "installer\$name"
    if (Test-Path $from) { Copy-Item $from (Join-Path $UpdRun $name) -Force }
    else { Warn "installer\$name is missing from this package; Admin > Updates can't update this server" }
}
$updScript = Join-Path $UpdRun "update.ps1"
$upAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$updScript`" -InstallDir `"$InstallDir`" -FromRequest" -WorkingDirectory $UpdRun
$upPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$upSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$upRunning = @(Get-ScheduledTask -TaskName $UpdateTask -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Running" })
if ($upRunning.Count) {
    # Setup was started by this very task (an update from Admin). Its
    # registration is the one in use and doesn't change between versions.
    Info "$UpdateTask is running this update; its registration is left as it is"
} else {
    Register-ScheduledTask -TaskName $UpdateTask -Action $upAction -Principal $upPrincipal -Settings $upSettings -Description "Runs F7FIVE0 updates when an admin starts one from the web app." -Force | Out-Null
}
if ($svcSid) {
    # Read + execute on the task lets that account start it (schtasks /Run).
    $sched = New-Object -ComObject Schedule.Service
    $sched.Connect()
    $upTask = $sched.GetFolder("\").GetTask($UpdateTask)
    $upSddl = $upTask.GetSecurityDescriptor(4)   # DACL only
    if ($upSddl -notmatch [regex]::Escape($svcSid)) { $upTask.SetSecurityDescriptor("$upSddl(A;;GRGX;;;$svcSid)", 0) }
}
Ok "scheduled task $UpdateTask registered (used by Admin > Updates)"

# ---------------------------------------------------------------------------
Step "Recording the version"
# ---------------------------------------------------------------------------
# version.json is what the API, Admin > Updates, and the updater's health check
# read. Setup passes appVersion; a release zip carries a VERSION file. Written
# before the services start, so a started API already reports it. Without a
# version (a git checkout) the file is left as it is.
$VersionNow = $AppVersion
if (-not $VersionNow) {
    $versionFile = Join-Path $SourceDir "VERSION"
    if (Test-Path $versionFile) { $VersionNow = (Get-Content $versionFile -Raw).Trim() }
}
if ($VersionNow -and (Test-SemVer $VersionNow)) {
    $VersionNow = $VersionNow.TrimStart("v")
    $record = [ordered]@{ version = $VersionNow; installed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
    [IO.File]::WriteAllText((Join-Path $InstallDir "version.json"), ($record | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Ok "version $VersionNow recorded"
    # Setup copied itself into data\updates\setup. Keep this version's copy and the previous one.
    Prune-SetupCache (Join-Path $UpdDir "setup") $VersionNow
} elseif ($VersionNow) {
    Warn "'$VersionNow' is not a version number; version.json was not written."
} else {
    Info "no version given; version.json left as it is"
}

# Command-line remote access (advanced and recovery). The Setup wizard
# installs for home use only and never runs this.
$PublicUrl = Get-EnvValue "PUBLIC_URL"
$raMethod = $RemoteAccess
if (-not $raMethod -and $TunnelToken) { $raMethod = "token" }
$RemoteAccessFailed = $false
if ($raMethod -and $raMethod -ne "none") {
    Step "Remote access: $raMethod"
    $raArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $raScript, "-InstallDir", $InstallDir, "-Method", $raMethod, "-NoRestart")
    if ($PublicHost) { $raArgs += @("-PublicHost", $PublicHost) }
    if ($DuckDnsToken) { $raArgs += @("-DuckDnsToken", $DuckDnsToken) }
    if ($TunnelToken) { $raArgs += @("-TunnelToken", $TunnelToken) }
    & powershell.exe @raArgs
    if ($LASTEXITCODE -eq 0) {
        $PublicUrl = Get-EnvValue "PUBLIC_URL"
    } else {
        $RemoteAccessFailed = $true
        Warn "Remote access is not set up. F7FIVE0 still works at home; finish it from Admin > Remote access."
    }
}

# ---------------------------------------------------------------------------
Step "Starting F7FIVE0"
# ---------------------------------------------------------------------------
foreach ($svc in $ServiceNames) { Start-Service -Name $svc }
function Wait-Http([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0 -ErrorAction Stop
            if ($r.StatusCode -lt 500) { return $true }
        } catch {
            $resp = $_.Exception.Response
            if ($resp -and [int]$resp.StatusCode -lt 500) { return $true }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}
$apiUp = Wait-Http "http://127.0.0.1:$ApiPort/api/health" 90
$webUp = Wait-Http "http://127.0.0.1:$WebPort/login" 90
if ($apiUp) { Ok "API is up" } else { Warn "API did not answer yet. Check $LogsDir\F7FIVE0-API.err.log" }
if ($webUp) { Ok "web app is up" } else { Warn "web app did not answer yet. Check $LogsDir\F7FIVE0-Web.err.log" }

# ---------------------------------------------------------------------------
# Summary (console, and logs\setup-summary.txt for the wizard's last page)
# ---------------------------------------------------------------------------
$lanOn = ($bind -eq "0.0.0.0")
$lan = @(Get-LanIPv4)
$publicNets = @()
if ($lanOn) {
    $publicNets = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.NetworkCategory -eq "Public" } | Select-Object -ExpandProperty Name)
}
$summary = New-Object System.Collections.Generic.List[string]
$attention = New-Object System.Collections.Generic.List[string]
$summary.Add("F7FIVE0 is installed.")
$summary.Add("")
$summary.Add("On this PC:  http://localhost:$WebPort")
if ($lanOn) {
    if ($lan.Count) { $summary.Add("At home:  http://$($lan[0]):$WebPort  (phones, TVs, other computers)") }
    foreach ($n in $publicNets) {
        $attention.Add("Windows treats the network '$n' as Public, so its firewall blocks phones and TVs. Set it to Private: Settings > Network & internet > (your Wi-Fi or Ethernet) > Network profile type > Private.")
    }
} else {
    $summary.Add("Home network access: off. Only this PC can open F7FIVE0.")
    $summary.Add("  To let phones and TVs connect, run in an elevated PowerShell:")
    $summary.Add("  & '$InstallDir\installer\install.ps1' -OpenFirewall 1")
}
if ($PublicUrl) {
    $summary.Add("From anywhere:  $PublicUrl")
} else {
    $summary.Add("Away from home: sign in and go to Admin > Remote access.")
}
if ($AndroidAppVersion) {
    $summary.Add("Android app $($AndroidAppVersion):  sign in on your phone's browser, then Account > Download for Android.")
}
if (-not $IsUpgrade) {
    $summary.Add("")
    $summary.Add("Sign in as '$AdminUser'. Your libraries fill in over the next few minutes.")
}
# A key saved later in Admin > Metadata lives in the database, so only a
# fresh install can tell for sure that there is none yet.
if (-not $IsUpgrade -and -not (Get-EnvValue "TMDB_API_KEY")) {
    $summary.Add("")
    $summary.Add("Next: add a free TMDB key for movie and show posters and descriptions.")
    $summary.Add("  Sign in, then Admin > Metadata. It walks you through getting one.")
}
foreach ($w in $script:Warnings) { $attention.Add($w) }
if ($attention.Count) {
    $summary.Add("")
    $summary.Add("Needs attention:")
    foreach ($w in $attention) { $summary.Add("- $w") }
}
Write-Host ""
foreach ($line in $summary) {
    $color = if ($line -like "- *" -or $line -eq "Needs attention:") { "Yellow" } elseif ($line -like "F7FIVE0 is installed*") { "Green" } else { "White" }
    Write-Host "  $line" -ForegroundColor $color
}
Write-Host "  Settings: $EnvFile   Logs: $LogsDir" -ForegroundColor Gray
Write-Host ""
$summaryFile = Join-Path $LogsDir "setup-summary.txt"
try { [IO.File]::WriteAllLines($summaryFile, $summary, (New-Object Text.UTF8Encoding($false))) } catch { }
# Let Users read Setup's own summary without elevation. Service logs stay private.
Grant-SetupLogRead $summaryFile
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full log: $LogFile" -ForegroundColor Yellow
    Write-Host "If Windows says access denied, open it from an elevated PowerShell." -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch { }
    try { Grant-SetupLogRead $LogFile } catch { }
    exit 1
}
try { Stop-Transcript | Out-Null } catch { }
# Re-grant after the transcript is closed so Users can read the finished log.
try { Grant-SetupLogRead $LogFile } catch { }
exit 0
