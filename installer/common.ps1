# Helpers shared by install.ps1 and remote-access.ps1. Dot-source it:
#   . (Join-Path $PSScriptRoot "common.ps1")
# Functions read the caller's variables at call time: $EnvFile, $Nssm,
# $LogsDir, $ServiceUser, $ServicePassword, and $RunLog (when set, every
# Info/Ok/Warn line is also appended to that file).

function Write-RunLog([string]$line) {
    if (-not $script:RunLog) { return }
    $stamp = (Get-Date).ToString("HH:mm:ss")
    for ($i = 0; $i -lt 3; $i++) {
        try { [IO.File]::AppendAllText($script:RunLog, "$stamp $line`r`n"); return } catch { Start-Sleep -Milliseconds 100 }
    }
}
function Info([string]$msg) { Write-Host "    $msg" -ForegroundColor Gray; Write-RunLog $msg }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green; Write-RunLog $msg }
function Warn([string]$msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow; Write-RunLog "[!] $msg"; $script:LastWarn = $msg; if ($null -ne $script:Warnings) { $script:Warnings.Add($msg) } }
function Fail([string]$msg) {
    $prefix = if ($script:FailPrefix) { $script:FailPrefix } else { "F7FIVE0 setup stopped" }
    throw "${prefix}: $msg"
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

# Runs winget and returns its exit code. 0 = installed;
# -1978335189 (0x8A15002B) = already installed / no upgrade available.
# Callers decide what counts as success: winget sometimes reports failure
# for an install that worked (seen with PostgreSQL), so check the result
# on disk too.
function Invoke-WingetRaw([string]$id, [string[]]$extra = @()) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "winget is not available. Install 'App Installer' from the Microsoft Store, then run Setup again."
    }
    Info "winget install $id"
    $wargs = @("install", "--id", $id, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity") + $extra
    & winget @wargs
    $rc = $LASTEXITCODE
    Refresh-Path
    return $rc
}

function Invoke-Winget([string]$id, [string[]]$extra = @()) {
    $rc = Invoke-WingetRaw $id $extra
    if ($rc -ne 0 -and $rc -ne -1978335189) {
        Fail "winget could not install $id (exit $rc)."
    }
}

function Set-PrivateAcl([string]$path) {
    # Only Administrators and SYSTEM can read files that hold secrets.
    & icacls $path /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null
}

function Get-EnvValue([string]$key) {
    if (-not (Test-Path $EnvFile)) { return "" }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$key\s*=(.*)$") { return $matches[1].Trim() }
    }
    return ""
}

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

# Registers (or re-registers) an NSSM service. Runs as $ServiceUser when the
# caller set one, otherwise as LocalSystem.
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
    if ($ExtraEnv.Count) { & $Nssm set $Name AppEnvironmentExtra @ExtraEnv *> $null }
    $ErrorActionPreference = $prev
    if (-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)) { Fail "could not register service $Name" }
    Info "registered $Name"
}

function Remove-Svc([string]$Name) {
    if (-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)) { return }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue
    if ($Nssm -and (Test-Path $Nssm)) { & $Nssm remove $Name confirm *> $null } else { & sc.exe delete $Name | Out-Null }
    $ErrorActionPreference = $prev
    Info "removed $Name"
}

# The machine's LAN IPv4 addresses (no loopback / link-local).
function Get-LanIPv4 {
    return @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress)
}
