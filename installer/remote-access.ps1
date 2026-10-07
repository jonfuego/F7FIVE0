<#
.SYNOPSIS
  Sets up, changes, or turns off remote access to F7FIVE0.

.DESCRIPTION
  Usually you never run this by hand: the web app's Admin > Remote access
  page starts it through the F7FIVE0-RemoteAccess scheduled task (runs as
  SYSTEM, registered by Setup). You can also run it from an elevated
  PowerShell in the install folder, for example:

    .\installer\remote-access.ps1 -Method tailscale
    .\installer\remote-access.ps1 -Method cloudflare -PublicHost music.yourdomain.com
    .\installer\remote-access.ps1 -Method portforward -PublicHost myname.duckdns.org -DuckDnsToken <token>
    .\installer\remote-access.ps1 -Method token -PublicHost music.yourdomain.com -TunnelToken <token>
    .\installer\remote-access.ps1 -Method off

  Methods:
    tailscale   : free, no domain. Browser sign-in, then Tailscale Funnel
                  publishes https://<name>.<tailnet>.ts.net
    cloudflare  : free tunnel on a domain already on Cloudflare. Browser
                  sign-in, then this creates the tunnel, the DNS record, and
                  an F7FIVE0-Tunnel service.
    portforward : Caddy on ports 80/443 with an automatic certificate. You
                  forward those ports on your router.
    token       : a tunnel made in the Cloudflare dashboard (its token).
    off         : stop publishing F7FIVE0 outside your home network.

  On success it saves PUBLIC_URL in .env and restarts F7FIVE0-API and
  F7FIVE0-Web so passkeys and links use the new address. Progress goes to
  data\remote-access\status.json and run.log, which the admin page reads.
#>
[CmdletBinding()]
param(
    [string] $InstallDir = "",
    [ValidateSet("", "tailscale", "cloudflare", "portforward", "token", "off")]
    [string] $Method = "",
    [string] $PublicHost = "",
    [string] $DuckDnsToken = "",
    [string] $TunnelToken = "",
    # Read the method and answers from data\remote-access\request.json (the
    # scheduled task passes this; the web app writes the request).
    [switch] $FromRequest,
    # Leave the F7FIVE0 services alone (install.ps1 starts them itself).
    [switch] $NoRestart
)

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $InstallDir) { $InstallDir = Split-Path -Parent $PSScriptRoot }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
. (Join-Path $PSScriptRoot "common.ps1")

# Pinned downloads (SEC-P0-2): exact version, immutable URL, and SHA-256 per
# file in installer\downloads.manifest.psd1. Get-DownloadSpec (common.ps1)
# reads them; the Download helper verifies the hash (and Authenticode, for the
# signed cloudflared exe and Tailscale MSI). Caddy ships as a zip we extract.
# winget does not work reliably as SYSTEM, so Tailscale comes straight from its MSI.
$CloudflaredSpec = Get-DownloadSpec "cloudflared"
$CaddySpec       = Get-DownloadSpec "caddy"
$TailscaleSpec   = Get-DownloadSpec "tailscale"

$BinDir   = Join-Path $InstallDir "bin"
$DataDir  = Join-Path $InstallDir "data"
$LogsDir  = Join-Path $InstallDir "logs"
$EnvFile  = Join-Path $InstallDir ".env"
$Nssm     = Join-Path $BinDir "nssm.exe"
# Remote-access services always run as LocalSystem; they need no share access.
$ServiceUser = ""
$ServicePassword = ""
$script:FailPrefix = "Remote access setup stopped"

$RaDir       = Join-Path $DataDir "remote-access"
$StatusFile  = Join-Path $RaDir "status.json"
$RequestFile = Join-Path $RaDir "request.json"
$CancelFile  = Join-Path $RaDir "cancel"
$CurrentFile = Join-Path $RaDir "current.json"
if (-not (Test-Path $RaDir)) { New-Item -ItemType Directory -Path $RaDir | Out-Null }
$script:RunLog = Join-Path $RaDir "run.log"
[IO.File]::WriteAllText($script:RunLog, "")

$script:Cancelled = $false
$script:LastWarn = ""
# Open sign-in links in a browser only when someone is at this console. The
# scheduled task runs as SYSTEM with no desktop; the admin page shows the link.
$OpenLinks = -not $FromRequest
$script:LastSave = Get-Date

# ---------------------------------------------------------------------------
# Status file (read by GET /api/admin/remote-access/run)
# ---------------------------------------------------------------------------
function Now-Iso { return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
$script:Status = [ordered]@{
    id = ([guid]::NewGuid().ToString("N")); method = $Method; host = $PublicHost
    state = "running"; step = "Starting"; sign_in_url = $null; sign_in_deadline = $null
    public_url = $null; error = $null
    started_at = (Now-Iso); updated_at = (Now-Iso); finished_at = $null
}
function Save-Status {
    $script:Status.updated_at = Now-Iso
    $script:LastSave = Get-Date
    $json = $script:Status | ConvertTo-Json -Depth 4
    $tmp = "$StatusFile.tmp"
    for ($i = 0; $i -lt 5; $i++) {
        try {
            [IO.File]::WriteAllText($tmp, $json, (New-Object Text.UTF8Encoding($false)))
            Move-Item -Force $tmp $StatusFile
            return
        } catch { Start-Sleep -Milliseconds 200 }
    }
}
function Set-RunStatus([hashtable]$changes) {
    foreach ($k in $changes.Keys) { $script:Status[$k] = $changes[$k] }
    Save-Status
}
function Step([string]$msg) {
    Write-Host ""
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-RunLog "== $msg"
    Set-RunStatus @{ step = $msg }
}
function Test-Cancel {
    if (Test-Path $CancelFile) { $script:Cancelled = $true }
    return $script:Cancelled
}

# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
$HostPattern  = '^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$'
$DuckPattern  = '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
$TokenPattern = '^[A-Za-z0-9_\-+/=]{40,4096}$'

$requestError = ""
if ($FromRequest) {
    # The request was written by the web app (possibly running as a
    # non-admin service account): treat every field as untrusted.
    try {
        $raw = Get-Content -Raw -Path $RequestFile
        # It can hold a token: delete it before anything else can fail.
        Remove-Item -Force $RequestFile -ErrorAction SilentlyContinue
        $req = $raw | ConvertFrom-Json
        $rid = [string]$req.id
        if ($rid -match '^[a-f0-9]{32}$') { $script:Status.id = $rid }
        $m = [string]$req.method
        if ($m -in @("tailscale", "cloudflare", "portforward", "token", "off")) { $Method = $m } else { $requestError = "Unknown remote access method." }
        $PublicHost = [string]$req.host
        $DuckDnsToken = [string]$req.duckdns_token
        $TunnelToken = [string]$req.tunnel_token
    } catch {
        $requestError = "Could not read the request from the web app."
    }
}
Remove-Item -Force $CancelFile -ErrorAction SilentlyContinue
$PublicHost = $PublicHost.Trim().ToLower()
$DuckDnsToken = $DuckDnsToken.Trim().ToLower()
$TunnelToken = $TunnelToken.Trim()
if (-not $requestError) {
    if (-not $Method) { $requestError = "Choose a method: -Method tailscale, cloudflare, portforward, token, or off." }
    elseif ($Method -in @("cloudflare", "portforward", "token") -and $PublicHost -notmatch $HostPattern) {
        $requestError = "Enter just the address, like music.yourdomain.com (no https:// and no slashes)."
    } elseif ($Method -eq "portforward" -and $DuckDnsToken -and $DuckDnsToken -notmatch $DuckPattern) {
        $requestError = "That DuckDNS token doesn't look right. Copy it from duckdns.org (it looks like 1a2b3c4d-....)."
    } elseif ($Method -eq "token" -and $TunnelToken -notmatch $TokenPattern) {
        $requestError = "That tunnel token doesn't look right. Copy the long token from the Cloudflare dashboard (the part after --token)."
    }
}
if ($Method -notin @("cloudflare", "portforward", "token")) { $PublicHost = "" }
if ($Method -ne "portforward" -or $PublicHost -notlike "*.duckdns.org") { $DuckDnsToken = "" }
if ($Method -ne "token") { $TunnelToken = "" }
$script:Status.method = $Method
$script:Status.host = $PublicHost

$WebPort = [int](Get-EnvValue "WEB_PORT")
if (-not $WebPort) { $WebPort = 3001 }
$ContactEmail = Get-EnvValue "MUSICBRAINZ_USER_AGENT_EMAIL"
$PrevMethod = ""
if (Test-Path $CurrentFile) {
    try { $PrevMethod = [string](Get-Content -Raw $CurrentFile | ConvertFrom-Json).method } catch { }
}
if (-not $PrevMethod -and (Get-EnvValue "PUBLIC_URL") -match '\.ts\.net/?$') { $PrevMethod = "tailscale" }

# ---------------------------------------------------------------------------
# Sign-in runner: starts a CLI that prints a sign-in link and waits for the
# person to finish in a browser. The link is put in the status file for the
# admin page (and opened in a browser when run from a console).
# ---------------------------------------------------------------------------
function Invoke-WithSignIn([string]$exe, [string]$argLine, [int]$timeoutSec, [bool]$openLinks, [scriptblock]$done) {
    $out = Join-Path $env:TEMP ("f7five0-" + [guid]::NewGuid().ToString("N") + ".log")
    $err = "$out.err"
    $p = Start-Process -FilePath $exe -ArgumentList $argLine -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle   # keeps ExitCode readable after the process ends
    $seen = @{}
    $shown = 0
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    $finished = $false
    while ((Get-Date) -lt $deadline) {
        $text = ""
        foreach ($f in @($out, $err)) { if (Test-Path $f) { $text += (Get-Content -Raw -Path $f -ErrorAction SilentlyContinue) + "`n" } }
        $newLines = @($text -split "`r?`n" | Where-Object { $_.Trim() })
        for ($i = $shown; $i -lt $newLines.Count; $i++) { Info $newLines[$i].Trim() }
        $shown = $newLines.Count
        foreach ($m in [regex]::Matches($text, 'https://(login\.tailscale\.com|dash\.cloudflare\.com)/\S+')) {
            $u = $m.Value.TrimEnd('.', ')', ',', '"', "'")
            if ($seen.ContainsKey($u)) { continue }
            $seen[$u] = $true
            Set-RunStatus @{ state = "signin"; sign_in_url = $u; sign_in_deadline = $deadline.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
            if ($openLinks) {
                Write-Host "    A browser window is opening. Sign in (or create a free account) there, then come back." -ForegroundColor Yellow
                try { Start-Process $u } catch { }
            }
        }
        if ($p.HasExited) { break }
        if ($done -and (& $done)) { $finished = $true; break }
        if (Test-Cancel) { break }
        if (((Get-Date) - $script:LastSave).TotalSeconds -ge 5) { Save-Status }
        Start-Sleep -Seconds 1
    }
    if (-not $p.HasExited) { try { $p.Kill() } catch { } }
    Remove-Item -Force $out, $err -ErrorAction SilentlyContinue
    Set-RunStatus @{ state = "running"; sign_in_url = $null; sign_in_deadline = $null }
    if ($script:Cancelled) { return $false }
    if ($done) { return ($finished -or [bool](& $done)) }
    return ($p.HasExited -and $p.ExitCode -eq 0)
}

# ---------------------------------------------------------------------------
# Methods. Each returns the public https URL, or $null after a Warn.
# ---------------------------------------------------------------------------
function Setup-Tailscale {
    $ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
    if (-not (Test-Path $ts)) {
        Step "Installing Tailscale"
        $msi = Join-Path $env:TEMP "f7five0-tailscale.msi"
        Download $TailscaleSpec.Url $msi $TailscaleSpec.Sha256 $TailscaleSpec.Publisher
        $p = Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$msi`" /quiet /norestart" -Wait -PassThru
        Remove-Item -Force $msi -ErrorAction SilentlyContinue
        if ($p.ExitCode -notin @(0, 3010)) { Warn "The Tailscale installer stopped (code $($p.ExitCode))." }
        for ($i = 0; $i -lt 30 -and -not (Test-Path $ts); $i++) { Start-Sleep -Seconds 2 }
    }
    if (-not (Test-Path $ts)) { Warn "Tailscale did not install. Install it from tailscale.com, then try again."; return $null }
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $state = { try { (& $ts status --json 2>$null | Out-String | ConvertFrom-Json) } catch { $null } }
        for ($i = 0; $i -lt 20 -and -not (& $state); $i++) { Start-Sleep -Seconds 2 }   # service warming up
        $st = & $state
        if (-not $st -or $st.BackendState -ne "Running") {
            Step "Signing in to Tailscale"
            Info "Sign in with Google, Microsoft, Apple, or GitHub (that creates a free Tailscale account if you're new)."
            # --unattended keeps the connection up when nobody is logged in to Windows.
            $ok = Invoke-WithSignIn $ts "up --unattended --hostname=f7five0 --timeout=0s" 900 $OpenLinks {
                $s = & $state; $s -and $s.BackendState -eq "Running"
            }
            if (-not $ok) { if (-not $script:Cancelled) { Warn "Tailscale sign-in did not finish in time." }; return $null }
        } else {
            Info "this PC is already signed in to Tailscale as $($st.Self.HostName)"
        }
        Step "Publishing F7FIVE0 with Tailscale Funnel"
        Info "The first time, Tailscale may ask you to allow Funnel for your account."
        $ok = Invoke-WithSignIn $ts "funnel --bg $WebPort" 600 $OpenLinks $null
        if (-not $ok) { if (-not $script:Cancelled) { Warn "Tailscale Funnel did not start." }; return $null }
        $dns = ((& $state).Self.DNSName).TrimEnd('.')
        if (-not $dns) { Warn "Could not read this PC's Tailscale name."; return $null }
        return "https://$dns"
    } finally { $ErrorActionPreference = $prev }
}

function Get-Cloudflared {
    $cfd = Join-Path $BinDir "cloudflared.exe"
    if (-not (Test-Path $cfd)) { Download $CloudflaredSpec.Url $cfd $CloudflaredSpec.Sha256 $CloudflaredSpec.Publisher }
    return $cfd
}

function Wait-ServiceRunning([string]$name, [int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        $s = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($s -and $s.Status -eq "Running") { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Setup-Cloudflare([string]$hostName) {
    $cfd = Get-Cloudflared
    $cfDir = Join-Path $InstallDir "cloudflared"
    if (-not (Test-Path $cfDir)) { New-Item -ItemType Directory -Path $cfDir | Out-Null }
    $cert = Join-Path $cfDir "cert.pem"
    $cred = Join-Path $cfDir "tunnel.json"
    $cfg  = Join-Path $cfDir "config.yml"
    $name = "f7five0"
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        if (-not (Test-Path $cert)) {
            Step "Signing in to Cloudflare"
            Info "Sign in to Cloudflare (or create a free account), then click the domain '$(($hostName -split '\.', 2)[1])' and Authorize."
            Info "Signed in but no Authorize page? Open the sign-in link again."
            $userCert = Join-Path $env:USERPROFILE ".cloudflared\cert.pem"
            if (Test-Path $userCert) { Move-Item -Force $userCert "$userCert.bak-f7five0" }
            # cloudflared gives up on its own after about 9 minutes.
            $ok = Invoke-WithSignIn $cfd "tunnel login" 540 $false { Test-Path $userCert }
            if (-not $ok) {
                if (Test-Path "$userCert.bak-f7five0") { Move-Item -Force "$userCert.bak-f7five0" $userCert }
                if (-not $script:Cancelled) { Warn "Cloudflare sign-in did not finish in time (Cloudflare allows about 9 minutes)." }
                return $null
            }
            Move-Item -Force $userCert $cert
            if (Test-Path "$userCert.bak-f7five0") { Move-Item -Force "$userCert.bak-f7five0" $userCert }
            Set-PrivateAcl $cert
        }
        Step "Creating the Cloudflare tunnel"
        # `tunnel list` only returns live tunnels. Don't filter on deleted_at:
        # live tunnels report it as "0001-01-01T00:00:00Z", not blank.
        $findTunnel = {
            $json = & $cfd tunnel --origincert $cert list --name $name --output json 2>$null | Out-String
            if (-not $json.Trim()) { return $null }
            try { @($json | ConvertFrom-Json) | Where-Object { $_.name -eq $name } | Select-Object -First 1 } catch { $null }
        }
        $tunnel = & $findTunnel
        if (-not $tunnel) {
            $out = @(& $cfd tunnel --origincert $cert create --credentials-file $cred $name 2>&1 | ForEach-Object { "$_" })
            $out | ForEach-Object { Info $_ }
            $tunnel = & $findTunnel
            if (-not $tunnel) { Warn "Could not create the Cloudflare tunnel."; return $null }
        }
        if (-not (Test-Path $cred)) {
            # The tunnel exists on Cloudflare (an earlier install) but this PC
            # has no credentials for it. Fetch them.
            Info "Found the existing '$name' tunnel on your Cloudflare account; fetching its credentials."
            & $cfd tunnel --origincert $cert token --cred-file $cred $name 2>&1 | Out-Null
            if (-not (Test-Path $cred)) {
                Info "Could not fetch them. Replacing the old tunnel with a new one."
                & $cfd tunnel --origincert $cert cleanup $name 2>&1 | ForEach-Object { Info "$_" }
                & $cfd tunnel --origincert $cert delete -f $name 2>&1 | ForEach-Object { Info "$_" }
                & $cfd tunnel --origincert $cert create --credentials-file $cred $name 2>&1 | ForEach-Object { Info "$_" }
                $tunnel = & $findTunnel
            }
        }
        if (-not $tunnel -or -not (Test-Path $cred)) { Warn "Cloudflare tunnel credentials are missing."; return $null }
        Set-PrivateAcl $cred
        Step "Pointing $hostName at the tunnel"
        & $cfd tunnel --origincert $cert route dns --overwrite-dns $name $hostName 2>&1 | ForEach-Object { Info "$_" }
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
        Step "Starting the tunnel service"
        # Its own service, so an existing 'Cloudflared' service is never touched.
        Install-Svc "F7FIVE0-Tunnel" $cfd "tunnel --no-autoupdate --config `"$cfg`" run" $cfDir @() "F7FIVE0 Cloudflare Tunnel"
        Start-Service -Name "F7FIVE0-Tunnel"
        if (-not (Wait-ServiceRunning "F7FIVE0-Tunnel" 30)) { Warn "The F7FIVE0-Tunnel service did not start. See $LogsDir\F7FIVE0-Tunnel.err.log"; return $null }
        return "https://$hostName"
    } finally { $ErrorActionPreference = $prev }
}

function Setup-TunnelToken([string]$hostName, [string]$token) {
    Step "Starting the Cloudflare tunnel"
    $cfd = Get-Cloudflared
    Install-Svc "F7FIVE0-Tunnel" $cfd "tunnel --no-autoupdate run --token $token" $BinDir @() "F7FIVE0 Cloudflare Tunnel"
    Start-Service -Name "F7FIVE0-Tunnel"
    if (-not (Wait-ServiceRunning "F7FIVE0-Tunnel" 30)) { Warn "The F7FIVE0-Tunnel service did not start. Check the token. Log: $LogsDir\F7FIVE0-Tunnel.err.log"; return $null }
    Ok "tunnel service running"
    Info "In the Cloudflare dashboard, give this tunnel the public hostname $hostName pointing at http://localhost:$WebPort"
    return "https://$hostName"
}

function Setup-PortForward([string]$hostName, [string]$duckToken) {
    Step "Setting up the HTTPS proxy (Caddy)"
    $caddy = Join-Path $BinDir "caddy.exe"
    if (-not (Test-Path $caddy)) {
        # Caddy ships as a verified zip (the GitHub release has no bare exe);
        # pull caddy.exe out of it.
        $caddyZip = Join-Path $env:TEMP "f7five0-caddy.zip"
        Download $CaddySpec.Url $caddyZip $CaddySpec.Sha256 $CaddySpec.Publisher
        $caddyUnz = Join-Path $env:TEMP "f7five0-caddy"
        if (Test-Path $caddyUnz) { Remove-Item -Recurse -Force $caddyUnz }
        Expand-Archive -Path $caddyZip -DestinationPath $caddyUnz -Force
        $caddyExe = Get-ChildItem -Path $caddyUnz -Recurse -Filter caddy.exe | Select-Object -First 1
        if (-not $caddyExe) { Remove-Item -Recurse -Force $caddyUnz, $caddyZip -ErrorAction SilentlyContinue; Warn "Caddy download did not contain caddy.exe."; return $null }
        Copy-Item $caddyExe.FullName $caddy -Force
        Remove-Item -Recurse -Force $caddyUnz, $caddyZip -ErrorAction SilentlyContinue
    }
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
    # Mark Caddy's traffic as coming from a trusted front door so the Next proxy
    # forwards the real client-IP headers to the backend (SEC-P1-1). Setup wrote
    # TRUSTED_PROXY_SECRET into .env and the web service env; send it as the
    # X-F7five0-Proxy header. Without it the backend attributes to loopback.
    $proxySecret = Get-EnvValue "TRUSTED_PROXY_SECRET"
    $markProxy = if ($proxySecret) { "`r`n        header_up X-F7five0-Proxy $proxySecret" } else { "" }
    $body = "$hostName {`r`n    reverse_proxy 127.0.0.1:$WebPort {$markProxy`r`n    }`r`n}`r`n"
    [IO.File]::WriteAllText($caddyfile, "# Written by F7FIVE0 setup. Caddy gets and renews the HTTPS certificate.`r`n$global$body", (New-Object Text.UTF8Encoding($false)))
    $proxyEnv = @("XDG_DATA_HOME=$caddyData", "XDG_CONFIG_HOME=$caddyData")
    Install-Svc "F7FIVE0-Proxy" $caddy "run --config `"$caddyfile`" --adapter caddyfile" $caddyDir $proxyEnv "F7FIVE0 HTTPS proxy (Caddy)"
    if (-not (Get-NetFirewallRule -DisplayName "F7FIVE0 HTTPS" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "F7FIVE0 HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow -Profile Any | Out-Null
    }
    Start-Service -Name "F7FIVE0-Proxy"
    if (-not (Wait-ServiceRunning "F7FIVE0-Proxy" 30)) { Warn "The F7FIVE0-Proxy service did not start. See $LogsDir\F7FIVE0-Proxy.err.log"; return $null }

    $lanIp = @(Get-LanIPv4) | Select-Object -First 1
    $publicIp = $null
    try { $publicIp = (Invoke-RestMethod -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).ToString().Trim() } catch { }
    $resolved = $null
    try { $resolved = (Resolve-DnsName -Name $hostName -Type A -DnsOnly -ErrorAction Stop | Where-Object { $_.IPAddress } | Select-Object -First 1).IPAddress } catch { }

    Warn "Finish on your router (one time): forward TCP ports 443 and 80 to $lanIp (this PC), and give this PC a fixed (reserved) IP so the rule keeps working."
    if ($publicIp -and $resolved -and $resolved -ne $publicIp) {
        Warn "$hostName points to $resolved, but this home's public IP is $publicIp. Update the DNS record (or DuckDNS) to $publicIp."
    } elseif ($publicIp -and -not $resolved) {
        Warn "$hostName does not resolve yet. Point it at $publicIp."
    }
    Info "Once the router forwards those ports, Caddy fetches the HTTPS certificate on its own (it keeps retrying until it works)."
    return "https://$hostName"
}

# Removes whatever an earlier method left running, except $keep.
function Disable-Other([string]$keep) {
    if ($keep -notin @("cloudflare", "token")) { Remove-Svc "F7FIVE0-Tunnel" }
    if ($keep -ne "portforward") {
        Remove-Svc "F7FIVE0-Proxy"
        Get-NetFirewallRule -DisplayName "F7FIVE0 HTTPS" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Unregister-ScheduledTask -TaskName "F7FIVE0-DuckDNS" -Confirm:$false -ErrorAction SilentlyContinue
    }
    $ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
    if ($keep -ne "tailscale" -and $PrevMethod -eq "tailscale" -and (Test-Path $ts)) {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & $ts funnel reset *> $null
        $ErrorActionPreference = $prev
        Info "Tailscale Funnel switched off (Tailscale itself stays installed and signed in)"
    }
}

function Restart-F7five0 {
    foreach ($svc in @("F7FIVE0-API", "F7FIVE0-Web")) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s -and $s.Status -eq "Running") {
            Info "restarting $svc"
            Restart-Service -Name $svc -Force
        }
    }
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
$exitCode = 0
try {
    Save-Status
    if ($requestError) { Fail $requestError }
    if (-not (Test-Path $Nssm)) { Fail "F7FIVE0 is not installed in $InstallDir (no bin\nssm.exe). Run Setup first." }
    Write-RunLog "method: $Method$(if ($PublicHost) { ", address: $PublicHost" })"

    $url = $null
    switch ($Method) {
        "tailscale"   { $url = Setup-Tailscale }
        "cloudflare"  { $url = Setup-Cloudflare $PublicHost }
        "portforward" { $url = Setup-PortForward $PublicHost $DuckDnsToken }
        "token"       { $url = Setup-TunnelToken $PublicHost $TunnelToken }
        "off"         { Step "Turning off remote access"; Disable-Other ""; $url = "" }
    }
    if ($script:Cancelled) {
        Info "cancelled"
        Set-RunStatus @{ state = "cancelled"; step = "Cancelled" }
        $exitCode = 2
    } elseif ($Method -ne "off" -and -not $url) {
        $why = if ($script:LastWarn) { $script:LastWarn } else { "Remote access did not finish." }
        Set-RunStatus @{ state = "failed"; error = $why }
        $exitCode = 1
    } else {
        Step "Saving the address"
        Set-EnvKey "PUBLIC_URL" $url
        # Keep read access for the services' account (none when SYSTEM).
        Set-PrivateAcl $EnvFile @(Get-ServiceAccountSid)
        if ($Method -eq "off") {
            Remove-Item -Force $CurrentFile -ErrorAction SilentlyContinue
            Ok "remote access is off. F7FIVE0 works on your home network only."
        } else {
            Disable-Other $Method
            $cur = [ordered]@{ method = $Method; host = $PublicHost; public_url = $url; since = (Now-Iso) }
            [IO.File]::WriteAllText($CurrentFile, ($cur | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
            Ok "F7FIVE0 will be reachable at $url"
        }
        Set-RunStatus @{ public_url = $url }
        if (-not $NoRestart) {
            Set-RunStatus @{ state = "restarting" }
            Step "Restarting F7FIVE0 to use the new address"
            Restart-F7five0
        }
        Set-RunStatus @{ state = "succeeded"; step = "Done" }
    }
} catch {
    $msg = $_.Exception.Message
    Write-Host $msg -ForegroundColor Red
    Write-RunLog "[x] $msg"
    Set-RunStatus @{ state = "failed"; error = $msg }
    $exitCode = 1
} finally {
    Remove-Item -Force $CancelFile -ErrorAction SilentlyContinue
    Set-RunStatus @{ finished_at = (Now-Iso); sign_in_url = $null; sign_in_deadline = $null }
}
exit $exitCode
