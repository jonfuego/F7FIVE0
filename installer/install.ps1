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
    7. Optionally opens the firewall for your home network and connects a
       Cloudflare Tunnel for access from anywhere.

  The Setup wizard (F7FIVE0-Setup.exe) runs this script for you. You can
  also run it by hand from an elevated PowerShell:

    powershell -ExecutionPolicy Bypass -File .\installer\install.ps1

  and it asks for anything it needs.

  Upgrading: run the new Setup.exe (or this script from the new release).
  Your .env, database, art, and watch history are kept.

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
    [ValidateSet("", "none", "tailscale", "cloudflare", "portforward")]
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

# Pinned downloads. Bump deliberately.
$NodeVersion   = "22.14.0"
$NodeZipUrl    = "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip"
$FfmpegZipUrl  = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$CloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$CaddyUrl      = "https://caddyserver.com/api/download?os=windows&arch=amd64"
$PythonWingetId = "Python.Python.3.12"
$PostgresWingetId = "PostgreSQL.PostgreSQL.16"
$NssmWingetId  = "NSSM.NSSM"

$ServiceNames = @("F7FIVE0-API", "F7FIVE0-Stream", "F7FIVE0-Web")
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
function Info([string]$msg) { Write-Host "    $msg" -ForegroundColor Gray }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { throw "F7FIVE0 setup stopped: $msg" }

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

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Download([string]$url, [string]$dest) {
    Info "downloading $url"
    $tmp = "$dest.partial"
    for ($i = 1; $i -le 3; $i++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
            Move-Item -Force $tmp $dest
            return
        } catch {
            if ($i -eq 3) { throw }
            Warn "download failed (attempt $i), retrying: $($_.Exception.Message)"
            Start-Sleep -Seconds (3 * $i)
        }
    }
}

function Invoke-Winget([string]$id, [string[]]$extra = @()) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "winget is not available. Install 'App Installer' from the Microsoft Store, then run Setup again."
    }
    Info "winget install $id"
    $wargs = @("install", "--id", $id, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity") + $extra
    & winget @wargs
    # 0 = installed; -1978335189 (0x8A15002B) = already installed / no upgrade.
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        Fail "winget could not install $id (exit $LASTEXITCODE)."
    }
    Refresh-Path
}

function Set-PrivateAcl([string]$path) {
    # Only Administrators and SYSTEM can read files that hold secrets.
    & icacls $path /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null
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
        $MoviesDir = Ask "Movies folder" ""
        $TvDir = Ask "TV shows folder" ""
        $MusicDir = Ask "Music folder" ""
        $MusicVideosDir = Ask "Music videos folder" ""
    }
    if (-not $WebPort) { $WebPort = [int](Ask "Web port" "3001") }
    if (-not $OpenFirewall) { $OpenFirewall = if (AskYesNo "Allow phones, TVs, and other PCs on your home network to connect?" $true) { "1" } else { "0" } }
    if (-not $RemoteAccess -and -not $TunnelToken -and -not $NonInteractive) {
        Info "Listen from anywhere?"
        Info "  1 = Tailscale (recommended). Free, no domain, no router changes."
        Info "      Tailscale limits Funnel bandwidth: great for music, a video stream or two;"
        Info "      high-bitrate video or several viewers at once may buffer."
        Info "  2 = Cloudflare. Free, no router changes, needs a domain already on Cloudflare."
        Info "      No F7FIVE0 bandwidth cap; Cloudflare's free-plan terms discourage heavy video."
        Info "  3 = Port forwarding (advanced). Free, full home upload speed, no middleman."
        Info "      Needs router access (forward ports 80 and 443) and a domain or free"
        Info "      DuckDNS name. Your PC is reachable directly from the internet."
        Info "  4 = Home network only"
        $pick = Ask "Choose 1, 2, 3, or 4" "1"
        $RemoteAccess = switch ($pick) { "2" { "cloudflare" } "3" { "portforward" } "4" { "none" } default { "tailscale" } }
        if ($RemoteAccess -in @("cloudflare", "portforward") -and -not $PublicHost) {
            $PublicHost = Ask "Address to use (for example music.yourdomain.com or myname.duckdns.org)" ""
        }
        if ($RemoteAccess -eq "portforward" -and $PublicHost -like "*.duckdns.org" -and -not $DuckDnsToken) {
            $DuckDnsToken = Ask "DuckDNS token (from duckdns.org, keeps the name pointed at your home)" ""
        }
    }
    foreach ($d in @($MoviesDir, $TvDir, $MusicDir, $MusicVideosDir)) {
        if ($d -and -not (Test-Path $d)) { Warn "Folder not found right now: $d (it will be scanned once it exists)." }
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
    Download $NodeZipUrl $zip
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
    Download $FfmpegZipUrl $zip
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
$Psql = Find-Psql
$PgInstalledNow = $false
if (-not $Psql -and -not $IsUpgrade) {
    if (-not $PgSuperPassword) { $PgSuperPassword = New-Secret 24 }
    Info "installing PostgreSQL 16 (this is the slow one, a few minutes)"
    Invoke-Winget $PostgresWingetId @("--override", "--mode unattended --unattendedmodeui none --superpassword `"$PgSuperPassword`" --serverport 5432 --enable-components server,commandlinetools")
    $Psql = Find-Psql
    if (-not $Psql) { Fail "PostgreSQL did not install. Install PostgreSQL 16 from postgresql.org, then run Setup again." }
    $PgInstalledNow = $true
    $pgNote = Join-Path $DataDir "postgres-superuser.txt"
    Set-Content -Path $pgNote -Value "PostgreSQL superuser 'postgres' password (created by F7FIVE0 setup):`r`n$PgSuperPassword" -Encoding ASCII
    Set-PrivateAcl $pgNote
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

# ---------------------------------------------------------------------------
Step "Database"
# ---------------------------------------------------------------------------
$DbPassword = $null
if (-not $IsUpgrade) {
    if (-not $PgSuperPassword) {
        $saved = Join-Path $DataDir "postgres-superuser.txt"
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
    if (-not $ready) { Fail "Could not sign in to PostgreSQL as 'postgres' on 127.0.0.1:5432 ($lastErr). Check the password and that the PostgreSQL service is running." }
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
# Existing keys always win, so an upgrade never clobbers your settings.
$existing = [ordered]@{}
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { $existing[$matches[1]] = $matches[2] }
    }
}
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
}
$lines = New-Object System.Collections.Generic.List[string]
if (-not (Test-Path $EnvFile)) {
    $lines.Add("# F7FIVE0 configuration. Written by setup; safe to edit.")
    $lines.Add("# Restart the F7FIVE0 services after changing anything here.")
    $lines.Add("# Every available key is documented in .env.example.")
    $lines.Add("")
} else {
    foreach ($line in Get-Content $EnvFile) { $lines.Add($line) }
}
# Ports are the exception: the services are registered with the ports chosen
# above, so .env must match them even when they changed on this run.
$portKeys = @{ "API_PORT" = "$ApiPort"; "STREAM_PORT" = "$StreamPort"; "WEB_PORT" = "$WebPort" }
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*(API_PORT|STREAM_PORT|WEB_PORT)\s*=') {
        $lines[$i] = "$($matches[1])=$($portKeys[$matches[1]])"
    }
}
$added = 0
foreach ($k in $want.Keys) {
    if ($existing.Contains($k)) { continue }
    if ($k -eq "DATABASE_URL" -and -not $want[$k]) { Fail ".env has no DATABASE_URL and none could be created." }
    $lines.Add("$k=$($want[$k])")
    $added++
}
[IO.File]::WriteAllLines($EnvFile, $lines, (New-Object Text.UTF8Encoding($false)))
Set-PrivateAcl $EnvFile
Ok ("{0} ({1} new setting(s))" -f $EnvFile, $added)

# ---------------------------------------------------------------------------
Step "Backend packages"
# ---------------------------------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    & $Py -m venv (Join-Path $BackendDir ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "could not create the Python virtual environment" }
}
& $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $VenvPy -m pip install --disable-pip-version-check -q -r (Join-Path $BackendDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install failed ($LASTEXITCODE)" }
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
function Install-Svc([string]$Name, [string]$Exe, [string]$AppArgs, [string]$WorkDir, [string[]]$ExtraEnv, [string]$Desc) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if (Get-Service -Name $Name -ErrorAction SilentlyContinue) {
        & $Nssm stop $Name *> $null
        & $Nssm remove $Name confirm *> $null
    }
    & $Nssm install $Name $Exe *> $null
    & $Nssm set $Name AppParameters $AppArgs *> $null
    & $Nssm set $Name AppDirectory $WorkDir *> $null
    & $Nssm set $Name DisplayName $Name *> $null
    & $Nssm set $Name Description $Desc *> $null
    & $Nssm set $Name Start SERVICE_AUTO_START *> $null
    & $Nssm set $Name AppStdout (Join-Path $LogsDir "$Name.out.log") *> $null
    & $Nssm set $Name AppStderr (Join-Path $LogsDir "$Name.err.log") *> $null
    & $Nssm set $Name AppRotateFiles 1 *> $null
    & $Nssm set $Name AppRotateOnline 1 *> $null
    & $Nssm set $Name AppRotateBytes 10485760 *> $null
    & $Nssm set $Name AppExit Default Restart *> $null
    & $Nssm set $Name AppRestartDelay 5000 *> $null
    if ($ServiceUser) {
        & $Nssm set $Name ObjectName $ServiceUser $ServicePassword *> $null
    }
    & $Nssm set $Name AppEnvironmentExtra @ExtraEnv *> $null
    $ErrorActionPreference = $prev
    if (-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)) { Fail "could not register service $Name" }
    Info "registered $Name"
}
$pyEnv = @("PYTHONPATH=$BackendDir", "PYTHONUNBUFFERED=1", "PYTHONIOENCODING=utf-8")
Install-Svc "F7FIVE0-API" $VenvPy "-m uvicorn app.main:app --host 127.0.0.1 --port $ApiPort --proxy-headers" $BackendDir $pyEnv "F7FIVE0 API"
# Single worker on purpose: the transcoder session registry is in-process.
Install-Svc "F7FIVE0-Stream" $VenvPy "-m uvicorn app.stream:app --host 127.0.0.1 --port $StreamPort --workers 1 --proxy-headers" $BackendDir $pyEnv "F7FIVE0 stream gateway"
# Listen on the network only when LAN access was chosen (or chosen on an
# earlier install). Tunnel-only installs stay on loopback.
$lanRule = Get-NetFirewallRule -DisplayName "F7FIVE0 web" -ErrorAction SilentlyContinue
$bind = if ($OpenFirewall -eq "1" -or $lanRule) { "0.0.0.0" } else { "127.0.0.1" }
$webEnv = @(
    "NODE_ENV=production", "PORT=$WebPort", "HOSTNAME=$bind",
    "API_ORIGIN=http://127.0.0.1:$ApiPort", "STREAM_ORIGIN=http://127.0.0.1:$StreamPort",
    "F7FIVE0_DOWNLOADS_DIR=$(Join-Path $DataDir 'downloads')",
    "NEXT_TELEMETRY_DISABLED=1"
)
Install-Svc "F7FIVE0-Web" $Node "`"$(Join-Path $WebDir 'server.js')`"" $WebDir $webEnv "F7FIVE0 web app"

if ($OpenFirewall -eq "1" -or $lanRule) {
    if ($lanRule) {
        # Follow a changed WEB_PORT.
        $lanRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -LocalPort $WebPort
    } else {
        New-NetFirewallRule -DisplayName "F7FIVE0 web" -Direction Inbound -Protocol TCP -LocalPort $WebPort -Action Allow -Profile Private,Domain | Out-Null
    }
    Ok "firewall open on port $WebPort for private networks"
    Info "If other devices cannot connect, make sure Windows marks your home network as Private."
}

# ---------------------------------------------------------------------------
# Remote access: reach F7FIVE0 from anywhere.
#   tailscale  : free, no domain. Browser sign-in (Google/Microsoft/Apple/
#                GitHub), then Tailscale Funnel publishes
#                https://<name>.<tailnet>.ts.net
#   cloudflare : free tunnel on a domain you already have on Cloudflare.
#                Browser sign-in, then setup creates the tunnel, the DNS
#                record, and an F7FIVE0-Tunnel service.
#   token      : advanced, a dashboard-made tunnel token (-TunnelToken).
# ---------------------------------------------------------------------------
function Set-EnvKey([string]$key, [string]$value) {
    $lines = New-Object System.Collections.Generic.List[string]
    $found = $false
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            if ($line -match "^\s*$key\s*=") { $lines.Add("$key=$value"); $found = $true }
            else { $lines.Add($line) }
        }
    }
    if (-not $found) { $lines.Add("$key=$value") }
    [IO.File]::WriteAllLines($EnvFile, $lines, (New-Object Text.UTF8Encoding($false)))
}

# Run a CLI that may pause for a browser sign-in. Output goes to temp files;
# any sign-in link it prints is opened in the browser once.
function Invoke-WithSignIn([string]$exe, [string]$argLine, [int]$timeoutSec, [bool]$openLinks, [scriptblock]$done) {
    $out = Join-Path $env:TEMP ("f7five0-" + [guid]::NewGuid().ToString("N") + ".log")
    $err = "$out.err"
    $p = Start-Process -FilePath $exe -ArgumentList $argLine -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle   # keeps ExitCode readable after the process ends
    $opened = @{}
    $shown = 0
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        $text = ""
        foreach ($f in @($out, $err)) { if (Test-Path $f) { $text += (Get-Content -Raw -Path $f -ErrorAction SilentlyContinue) + "`n" } }
        $newLines = @($text -split "`r?`n" | Where-Object { $_.Trim() })
        for ($i = $shown; $i -lt $newLines.Count; $i++) { Info $newLines[$i].Trim() }
        $shown = $newLines.Count
        foreach ($m in [regex]::Matches($text, 'https://login\.tailscale\.com/\S+')) {
            $u = $m.Value.TrimEnd('.', ')', ',')
            if ($openLinks -and -not $opened.ContainsKey($u)) {
                $opened[$u] = $true
                Write-Host "    A browser window is opening. Sign in (or create a free account) there, then come back." -ForegroundColor Yellow
                Start-Process $u
            }
        }
        if ($p.HasExited) { break }
        if ($done -and (& $done)) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $p.HasExited) {
        if ($done -and (& $done)) { try { $p.Kill() } catch { } }
        else { try { $p.Kill() } catch { }; Remove-Item -Force $out, $err -ErrorAction SilentlyContinue; return $false }
    }
    Remove-Item -Force $out, $err -ErrorAction SilentlyContinue
    if ($done) { return [bool](& $done) }
    return ($p.ExitCode -eq 0)
}

function Setup-Tailscale {
    $ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
    if (-not (Test-Path $ts)) {
        Invoke-Winget "Tailscale.Tailscale" @("--scope", "machine")
        for ($i = 0; $i -lt 30 -and -not (Test-Path $ts); $i++) { Start-Sleep -Seconds 2 }
    }
    if (-not (Test-Path $ts)) { Warn "Tailscale did not install. Install it from tailscale.com, then run: installer\install.ps1 -RemoteAccess tailscale"; return $null }
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $state = { try { (& $ts status --json 2>$null | Out-String | ConvertFrom-Json) } catch { $null } }
        for ($i = 0; $i -lt 20 -and -not (& $state); $i++) { Start-Sleep -Seconds 2 }   # service warming up
        $st = & $state
        if (-not $st -or $st.BackendState -ne "Running") {
            Info "Signing this PC in to Tailscale (free). If you're new, pick Google, Microsoft, Apple, or GitHub to create an account."
            # --unattended keeps the connection up when nobody is logged in to Windows.
            $ok = Invoke-WithSignIn $ts "up --unattended --hostname=f7five0 --timeout=0s" 900 $true {
                $s = & $state; $s -and $s.BackendState -eq "Running"
            }
            if (-not $ok) { Warn "Tailscale sign-in did not finish. Run: installer\install.ps1 -RemoteAccess tailscale"; return $null }
        } else {
            Info "this PC is already signed in to Tailscale as $($st.Self.HostName)"
        }
        Info "publishing F7FIVE0 with Tailscale Funnel (the first time, Tailscale may ask you to allow Funnel in the browser)"
        $ok = Invoke-WithSignIn $ts "funnel --bg $WebPort" 600 $true $null
        if (-not $ok) { Warn "Tailscale Funnel did not start. Run: installer\install.ps1 -RemoteAccess tailscale"; return $null }
        $dns = ((& $state).Self.DNSName).TrimEnd('.')
        if (-not $dns) { Warn "Could not read this PC's Tailscale name."; return $null }
        return "https://$dns"
    } finally { $ErrorActionPreference = $prev }
}

function Setup-Cloudflare([string]$hostName) {
    if (-not $hostName) { Warn "No address given for Cloudflare (for example music.yourdomain.com). Skipping."; return $null }
    $cfd = Join-Path $BinDir "cloudflared.exe"
    if (-not (Test-Path $cfd)) { Download $CloudflaredUrl $cfd }
    $cfDir = Join-Path $InstallDir "cloudflared"
    if (-not (Test-Path $cfDir)) { New-Item -ItemType Directory -Path $cfDir | Out-Null }
    $cert = Join-Path $cfDir "cert.pem"
    $cred = Join-Path $cfDir "tunnel.json"
    $cfg  = Join-Path $cfDir "config.yml"
    $name = "f7five0"
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        if (-not (Test-Path $cert)) {
            Info "A browser window will open. Sign in to Cloudflare (or create a free account), then click the domain '$(($hostName -split '\.', 2)[1])' and Authorize."
            $userCert = Join-Path $env:USERPROFILE ".cloudflared\cert.pem"
            if (Test-Path $userCert) { Move-Item -Force $userCert "$userCert.bak-f7five0" }
            $ok = Invoke-WithSignIn $cfd "tunnel login" 900 $false { Test-Path $userCert }
            if (-not $ok) { Warn "Cloudflare sign-in did not finish. Run: installer\install.ps1 -RemoteAccess cloudflare -PublicHost $hostName"; return $null }
            Move-Item -Force $userCert $cert
            if (Test-Path "$userCert.bak-f7five0") { Move-Item -Force "$userCert.bak-f7five0" $userCert }
            Set-PrivateAcl $cert
        }
        $list = & $cfd tunnel --origincert $cert list --output json 2>$null | Out-String
        $tunnel = @($list | ConvertFrom-Json -ErrorAction SilentlyContinue) | Where-Object { $_.name -eq $name -and -not $_.deleted_at } | Select-Object -First 1
        if (-not $tunnel) {
            & $cfd tunnel --origincert $cert create --credentials-file $cred $name | ForEach-Object { Info $_ }
            if ($LASTEXITCODE -ne 0) { Warn "Could not create the Cloudflare tunnel."; return $null }
            $list = & $cfd tunnel --origincert $cert list --output json 2>$null | Out-String
            $tunnel = @($list | ConvertFrom-Json) | Where-Object { $_.name -eq $name } | Select-Object -First 1
        } elseif (-not (Test-Path $cred)) {
            & $cfd tunnel --origincert $cert token --cred-file $cred $name | Out-Null
        }
        if (-not $tunnel -or -not (Test-Path $cred)) { Warn "Cloudflare tunnel credentials are missing."; return $null }
        Set-PrivateAcl $cred
        & $cfd tunnel --origincert $cert route dns --overwrite-dns $name $hostName | ForEach-Object { Info $_ }
        if ($LASTEXITCODE -ne 0) { Warn "Could not point $hostName at the tunnel. Is that domain on the Cloudflare account you picked?"; return $null }
        $yaml = @(
            "# Written by F7FIVE0 setup.",
            "tunnel: $($tunnel.id)",
            "credentials-file: $cred",
            "ingress:",
            "  - hostname: $hostName",
            "    service: http://127.0.0.1:$WebPort",
            "  - service: http_status:404"
        )
        [IO.File]::WriteAllLines($cfg, $yaml, (New-Object Text.UTF8Encoding($false)))
        # Its own service, so an existing 'Cloudflared' service is never touched.
        Install-Svc "F7FIVE0-Tunnel" $cfd "tunnel --no-autoupdate --config `"$cfg`" run" $cfDir @() "F7FIVE0 Cloudflare Tunnel"
        Start-Service -Name "F7FIVE0-Tunnel"
        return "https://$hostName"
    } finally { $ErrorActionPreference = $prev }
}

function Setup-PortForward([string]$hostName, [string]$duckToken) {
    if (-not $hostName) { Warn "No address given for port forwarding (for example music.yourdomain.com or myname.duckdns.org). Skipping."; return $null }
    $caddy = Join-Path $BinDir "caddy.exe"
    if (-not (Test-Path $caddy)) { Download $CaddyUrl $caddy }
    $caddyDir = Join-Path $InstallDir "caddy"
    $caddyData = Join-Path $DataDir "caddy"
    foreach ($d in @($caddyDir, $caddyData)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null } }

    foreach ($port in 80, 443) {
        $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Where-Object { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName -ne "caddy" }
        if ($busy) { Warn "Port $port is already used by another program (often IIS or another web server). HTTPS will not work until it is freed." }
    }

    # Keep a DuckDNS name pointed at this home's public IP.
    if ($duckToken -and $hostName -like "*.duckdns.org") {
        $sub = $hostName -replace '\.duckdns\.org$', ''
        $updateUrl = "https://www.duckdns.org/update?domains=$sub&token=$duckToken&ip="
        try {
            $r = Invoke-RestMethod -Uri $updateUrl -UseBasicParsing -TimeoutSec 15
            if ("$r" -match "OK") { Ok "DuckDNS updated for $hostName" } else { Warn "DuckDNS did not accept the update ($r). Check the token." }
        } catch { Warn "Could not reach DuckDNS: $($_.Exception.Message)" }
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"Invoke-RestMethod -UseBasicParsing '$updateUrl' | Out-Null`""
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName "F7FIVE0-DuckDNS" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
        Ok "DuckDNS will be refreshed every 5 minutes (scheduled task F7FIVE0-DuckDNS)"
    }

    $caddyfile = Join-Path $caddyDir "Caddyfile"
    $global = if ($ContactEmail) { "{`r`n    email $ContactEmail`r`n}`r`n`r`n" } else { "" }
    $body = "$hostName {`r`n    reverse_proxy 127.0.0.1:$WebPort`r`n}`r`n"
    [IO.File]::WriteAllText($caddyfile, "# Written by F7FIVE0 setup. Caddy gets and renews the HTTPS certificate.`r`n$global$body", (New-Object Text.UTF8Encoding($false)))
    $proxyEnv = @("XDG_DATA_HOME=$caddyData", "XDG_CONFIG_HOME=$caddyData")
    Install-Svc "F7FIVE0-Proxy" $caddy "run --config `"$caddyfile`" --adapter caddyfile" $caddyDir $proxyEnv "F7FIVE0 HTTPS proxy (Caddy)"
    if (-not (Get-NetFirewallRule -DisplayName "F7FIVE0 HTTPS" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "F7FIVE0 HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow -Profile Any | Out-Null
    }
    Start-Service -Name "F7FIVE0-Proxy"

    $lanIp = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress | Select-Object -First 1)
    $publicIp = $null
    try { $publicIp = (Invoke-RestMethod -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).ToString().Trim() } catch { }
    $resolved = $null
    try { $resolved = (Resolve-DnsName -Name $hostName -Type A -DnsOnly -ErrorAction Stop | Where-Object { $_.IPAddress } | Select-Object -First 1).IPAddress } catch { }

    Write-Host ""
    Write-Host "    Finish on your router (one time):" -ForegroundColor Yellow
    Write-Host "      Forward TCP port 443 and TCP port 80 to $lanIp (this PC)." -ForegroundColor Yellow
    Write-Host "      Give this PC a fixed/reserved IP in the router so the rule keeps working." -ForegroundColor Yellow
    if ($publicIp -and $resolved -and $resolved -ne $publicIp) {
        Warn "$hostName points to $resolved, but this home's public IP is $publicIp. Update the DNS record (or DuckDNS) to $publicIp."
    } elseif ($publicIp -and -not $resolved) {
        Warn "$hostName does not resolve yet. Point it at $publicIp."
    }
    Info "Once the router forwards those ports, Caddy fetches the HTTPS certificate on its own (retries until it works)."
    return "https://$hostName"
}

$PublicUrl = $null
if ($RemoteAccess -eq "tailscale") {
    Step "Remote access: Tailscale"
    $PublicUrl = Setup-Tailscale
} elseif ($RemoteAccess -eq "cloudflare") {
    Step "Remote access: Cloudflare"
    $PublicUrl = Setup-Cloudflare $PublicHost
} elseif ($RemoteAccess -eq "portforward") {
    Step "Remote access: port forwarding (advanced)"
    $PublicUrl = Setup-PortForward $PublicHost $DuckDnsToken
} elseif ($TunnelToken) {
    Step "Remote access: Cloudflare tunnel token"
    $cfd = Join-Path $BinDir "cloudflared.exe"
    if (-not (Test-Path $cfd)) { Download $CloudflaredUrl $cfd }
    Install-Svc "F7FIVE0-Tunnel" $cfd "tunnel --no-autoupdate run --token $TunnelToken" $BinDir @() "F7FIVE0 Cloudflare Tunnel"
    Start-Service -Name "F7FIVE0-Tunnel"
    Ok "tunnel connected. In the Cloudflare dashboard, give it a public hostname pointing at http://localhost:$WebPort"
    if ($PublicHost) { $PublicUrl = "https://$PublicHost" }
}
if ($PublicUrl) {
    Set-EnvKey "PUBLIC_URL" $PublicUrl
    Set-PrivateAcl $EnvFile
    Ok "F7FIVE0 will be reachable at $PublicUrl"
} elseif ($RemoteAccess -in @("tailscale", "cloudflare", "portforward")) {
    Warn "Remote access is not set up yet. F7FIVE0 still works at home; rerun setup to try again."
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

$lan = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -ExpandProperty IPAddress)
Write-Host ""
Write-Host "  F7FIVE0 is installed." -ForegroundColor Green
Write-Host "  On this PC:        http://localhost:$WebPort" -ForegroundColor White
if ($OpenFirewall -eq "1" -and $lan.Count) {
    Write-Host "  On your network:   http://$($lan[0]):$WebPort" -ForegroundColor White
}
if ($PublicUrl) {
    Write-Host "  From anywhere:     $PublicUrl" -ForegroundColor White
    Write-Host "  (Your Account page shows a QR code for this address, handy for phones.)" -ForegroundColor Gray
}
if (-not $IsUpgrade) {
    Write-Host "  Sign in as '$AdminUser'. Your libraries fill in over the next few minutes." -ForegroundColor Gray
}
Write-Host "  Settings: $EnvFile   Logs: $LogsDir" -ForegroundColor Gray
Write-Host ""
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full log: $LogFile" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}
try { Stop-Transcript | Out-Null } catch { }
exit 0
