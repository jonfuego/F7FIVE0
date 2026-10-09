# Helpers shared by install.ps1, remote-access.ps1, and update.ps1. Dot-source it:
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

# Turns off QuickEdit for this script's own console window. With QuickEdit on,
# one click in the window starts a text selection ("Select" in the title bar)
# and Windows pauses the script until Esc or Enter: a Setup that looks hung
# for hours. Only this console changes, only for this run. No console (a
# scheduled task, redirected output) is fine: it returns $false.
function Disable-ConsoleQuickEdit {
    try {
        if (-not ("F7Five0.ConsoleMode" -as [type])) {
            Add-Type -Namespace F7Five0 -Name ConsoleMode -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
        }
        $stdin = [F7Five0.ConsoleMode]::GetStdHandle(-10)
        $mode = [uint32]0
        if (-not [F7Five0.ConsoleMode]::GetConsoleMode($stdin, [ref]$mode)) { return $false }
        # Clear ENABLE_QUICK_EDIT_MODE (0x40); ENABLE_EXTENDED_FLAGS (0x80) makes it stick.
        $new = ($mode -band (-bnot [uint32]0x40)) -bor [uint32]0x80
        return [F7Five0.ConsoleMode]::SetConsoleMode($stdin, $new)
    } catch {
        return $false
    }
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

# Reads installer\downloads.manifest.psd1 (next to this file) and returns the
# entry for $key: a hashtable with Name, Version, Url, Sha256, and Publisher.
# Every file Setup downloads is pinned there (SEC-P0-2). Cached per run.
function Get-DownloadSpec([string]$key) {
    if (-not $script:DownloadManifest) {
        $path = Join-Path $PSScriptRoot "downloads.manifest.psd1"
        if (-not (Test-Path $path)) { Fail "download manifest not found: $path" }
        $script:DownloadManifest = Import-PowerShellDataFile -Path $path
    }
    $spec = $script:DownloadManifest[$key]
    if (-not $spec) { Fail "no pinned download '$key' in downloads.manifest.psd1" }
    return $spec
}

# Downloads $url to $dest and verifies it against $expectedSha256 (SEC-P0-2).
# The hash is REQUIRED: a blank or missing expected hash is a hard error, so a
# call can never skip verification by accident. On mismatch the file is removed
# and the function throws, naming both the expected and the actual hash. When
# $publisher is given, the file must also carry a Valid Authenticode signature
# whose subject contains that string (used for signed exe/msi; leave blank for
# zips and unsigned binaries, which the SHA-256 already pins).
function Download([string]$url, [string]$dest, [string]$expectedSha256, [string]$publisher = "") {
    if ([string]::IsNullOrWhiteSpace($expectedSha256)) {
        Fail "refusing to download $url without an expected SHA-256 (SEC-P0-2)."
    }
    $want = $expectedSha256.Trim().ToUpperInvariant()
    Info "downloading $url"
    $tmp = "$dest.partial"
    $downloaded = $false
    for ($i = 1; $i -le 3; $i++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
            $downloaded = $true
            break
        } catch {
            if ($i -eq 3) { throw }
            Warn "download failed (attempt $i), retrying: $($_.Exception.Message)"
            Start-Sleep -Seconds (3 * $i)
        }
    }
    if (-not $downloaded) { throw "download of $url failed" }
    $got = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($got -ne $want) {
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
        throw "SHA-256 mismatch for $url : expected $want, got $got. The file was removed."
    }
    if ($publisher) {
        $sig = Get-AuthenticodeSignature -FilePath $tmp
        $subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
        if ($sig.Status -ne "Valid" -or $subject -notlike "*$publisher*") {
            Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            throw "Authenticode check failed for $url : status '$($sig.Status)', subject '$subject' (expected a Valid signature from '$publisher'). The file was removed."
        }
    }
    Move-Item -Force $tmp $dest
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
    # Send winget's text to the console and log, never to the pipeline:
    # anything left in the pipeline becomes part of this function's return
    # value, and the caller then sees "Found Python ... 0" instead of 0.
    # No 2>&1: under ErrorActionPreference Stop that turns stderr into errors.
    & winget @wargs | ForEach-Object {
        $line = "$_".Trim()
        if ($line -and $line -notmatch '^[-\\|/ ]+$') { Info $line }
    }
    $rc = [int]$LASTEXITCODE
    Refresh-Path
    return $rc
}

function Invoke-Winget([string]$id, [string[]]$extra = @()) {
    $rc = Invoke-WingetRaw $id $extra
    if ($rc -ne 0 -and $rc -ne -1978335189) {
        Fail "winget could not install $id (exit $rc)."
    }
}

function Set-PrivateAcl([string]$path, [string[]]$readers = @()) {
    # Only Administrators and SYSTEM can read files that hold secrets, plus
    # any account SIDs passed in $readers (read only).
    $grants = @("*S-1-5-32-544:F", "*S-1-5-18:F")
    foreach ($sid in $readers) { if ($sid) { $grants += "*${sid}:R" } }
    & icacls $path /inheritance:r /grant:r @grants | Out-Null
}

# SID for a Windows account name, or $null when it can't be resolved.
function Get-AccountSid([string]$account) {
    if (-not $account) { return $null }
    if ($account.StartsWith(".\")) { $account = "$env:COMPUTERNAME\" + $account.Substring(2) }
    try { return (New-Object Security.Principal.NTAccount($account)).Translate([Security.Principal.SecurityIdentifier]).Value }
    catch { return $null }
}

# SID of the account the F7FIVE0 services run as: $ServiceUser when the caller
# set one, otherwise whatever F7FIVE0-API is registered with. $null for
# LocalSystem (SYSTEM already has full control everywhere).
function Get-ServiceAccountSid {
    $account = $ServiceUser
    if (-not $account) {
        $svc = Get-CimInstance Win32_Service -Filter "Name='F7FIVE0-API'" -ErrorAction SilentlyContinue
        if ($svc) { $account = $svc.StartName }
    }
    if (-not $account -or $account -match '^(LocalSystem|NT AUTHORITY\\)') { return $null }
    return Get-AccountSid $account
}

# Locks the install folder. The services run code from it (as LocalSystem
# unless -ServiceUser), and C:\ lets any signed-in user change new subfolders,
# so: owner Administrators, no inherited rights, Administrators and SYSTEM
# full control, Users read and run. data\ and logs\ drop Users and give the
# service account (when there is one) modify. Code folders lose any explicit
# entries so a folder made before setup can't keep extra rights. Files that
# hold secrets (.env, data\remote-access) get their own ACLs afterwards.
function Set-InstallAcl([string]$root, [string]$serviceSid) {
    $admins = "*S-1-5-32-544"
    & icacls $root /setowner $admins /T /C /Q | Out-Null
    & icacls $root /reset /C /Q | Out-Null
    & icacls $root /inheritance:r /grant:r "${admins}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "could not set permissions on $root (icacls $LASTEXITCODE)" }
    foreach ($name in @("backend", "web", "runtime", "bin", "scripts", "installer", "android")) {
        $p = Join-Path $root $name
        if (Test-Path $p) { & icacls $p /reset /T /C /Q | Out-Null }
    }
    # Top-level files too (alembic.ini is read by a command run as admin);
    # .env keeps its private ACL.
    foreach ($f in Get-ChildItem $root -File -Force) {
        if ($f.Name -ne ".env") { & icacls $f.FullName /reset /C /Q | Out-Null }
    }
    foreach ($name in @("data", "logs")) {
        $p = Join-Path $root $name
        if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
        $grants = @("${admins}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F")
        if ($serviceSid) { $grants += "*${serviceSid}:(OI)(CI)M" }
        & icacls $p /reset /C /Q | Out-Null
        & icacls $p /inheritance:r /grant:r @grants /C /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "could not set permissions on $p (icacls $LASTEXITCODE)" }
    }
    # logs\: let Users open and list the folder so a non-elevated window can
    # reach Setup's own logs. This grant is on the folder object only, with no
    # (OI)/(CI), so new service log files (F7FIVE0-*.out/err.log) do not inherit
    # Users access and stay Administrators + SYSTEM + service account. Setup's
    # own files (install-*.log, setup-summary.txt) get Users read added by
    # Grant-SetupLogRead after they are written.
    $logsDir = Join-Path $root "logs"
    & icacls $logsDir /grant:r "*S-1-5-32-545:(RX)" /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "could not grant Users list on $logsDir (icacls $LASTEXITCODE)" }
}

# Grants Users (BUILTIN\Users) read on one of Setup's own log files, with no
# inheritance (it is a file). Call it after the file exists. Service logs are
# never passed here, so they keep their Administrators + SYSTEM + service
# account ACL. Safe to call again on a re-run (icacls /grant replaces the
# existing Users entry).
function Grant-SetupLogRead([string]$path) {
    if (-not $path -or -not (Test-Path $path)) { return }
    & icacls $path /grant:r "*S-1-5-32-545:(R)" /C /Q | Out-Null
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
# caller set one, otherwise as LocalSystem. When the caller set
# $script:KeepServiceAccount (an upgrade of an install whose services run as a
# Windows account), an existing service is changed in place instead of removed
# and re-created, so it keeps that account: Setup can't ask for the password again.
function Install-Svc([string]$Name, [string]$Exe, [string]$AppArgs, [string]$WorkDir, [string[]]$ExtraEnv, [string]$Desc) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exists = [bool](Get-Service -Name $Name -ErrorAction SilentlyContinue)
    if ($exists -and $script:KeepServiceAccount -and -not $ServiceUser) {
        & $Nssm stop $Name *> $null
        & $Nssm set $Name Application $Exe *> $null
    } else {
        if ($exists) {
            & $Nssm stop $Name *> $null
            & $Nssm remove $Name confirm *> $null
        }
        & $Nssm install $Name $Exe *> $null
    }
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

# ---------------------------------------------------------------------------
# Versions. Setup's versions are X.Y.Z, or X.Y.Z-label for a test build
# (0.1.0-batch4). Semantic versioning: a prerelease sorts below its release.
# ---------------------------------------------------------------------------
$script:SemVerRx = '^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$'

function Test-SemVer([string]$v) {
    if ([string]::IsNullOrEmpty($v)) { return $false }
    return [bool]($v -match $script:SemVerRx)
}

function ConvertTo-SemVerParts([string]$v) {
    if ([string]::IsNullOrEmpty($v) -or $v -notmatch $script:SemVerRx) { throw "not a version: '$v'" }
    $pre = @()
    if ($matches[4]) { $pre = @($matches[4] -split '\.') }
    return @{ Core = @([int]$matches[1], [int]$matches[2], [int]$matches[3]); Pre = $pre }
}

# -1, 0, or 1. Throws when either side isn't a version.
function Compare-SemVer([string]$a, [string]$b) {
    $pa = ConvertTo-SemVerParts $a
    $pb = ConvertTo-SemVerParts $b
    for ($i = 0; $i -lt 3; $i++) {
        if ($pa.Core[$i] -ne $pb.Core[$i]) {
            if ($pa.Core[$i] -lt $pb.Core[$i]) { return -1 }
            return 1
        }
    }
    if ($pa.Pre.Count -eq 0 -and $pb.Pre.Count -eq 0) { return 0 }
    if ($pa.Pre.Count -eq 0) { return 1 }
    if ($pb.Pre.Count -eq 0) { return -1 }
    $n = [Math]::Min($pa.Pre.Count, $pb.Pre.Count)
    for ($i = 0; $i -lt $n; $i++) {
        $x = [string]$pa.Pre[$i]
        $y = [string]$pb.Pre[$i]
        $xNum = $x -match '^\d+$'
        $yNum = $y -match '^\d+$'
        if ($xNum -and $yNum) {
            if ([decimal]$x -ne [decimal]$y) {
                if ([decimal]$x -lt [decimal]$y) { return -1 }
                return 1
            }
        } elseif ($xNum) { return -1 }
        elseif ($yNum) { return 1 }
        else {
            $c = [string]::CompareOrdinal($x, $y)
            if ($c -ne 0) { return [Math]::Sign($c) }
        }
    }
    return [Math]::Sign($pa.Pre.Count - $pb.Pre.Count)
}

# ---------------------------------------------------------------------------
# .env merge (install.ps1). Existing keys ALWAYS win, so an upgrade, including
# a silent one run by the updater, never blanks a setting: the contact email,
# the TMDB key, ports, library folders, secrets, anything added by hand. Keys in
# $Want that are missing get appended; the three port keys in $PortKeys are
# rewritten to the ports chosen for this run (the services are registered with
# them, so .env must match). Returns how many keys were added.
# ---------------------------------------------------------------------------
function Merge-EnvFile([string]$Path, $Want, [hashtable]$PortKeys) {
    $existing = @{}
    $lines = New-Object System.Collections.Generic.List[string]
    if (Test-Path $Path) {
        foreach ($line in Get-Content $Path) {
            $lines.Add($line)
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { $existing[$matches[1]] = $matches[2] }
        }
    } else {
        $lines.Add("# F7FIVE0 configuration. Written by setup; safe to edit.")
        $lines.Add("# Restart the F7FIVE0 services after changing anything here.")
        $lines.Add("# Every available key is documented in .env.example.")
        $lines.Add("")
    }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*(API_PORT|STREAM_PORT|WEB_PORT)\s*=') {
            $key = $matches[1]
            if ($PortKeys.ContainsKey($key)) { $lines[$i] = "$key=$($PortKeys[$key])" }
        }
    }
    $added = 0
    foreach ($k in $Want.Keys) {
        if ($existing.ContainsKey($k)) { continue }
        if ($k -eq "DATABASE_URL" -and -not $Want[$k]) { Fail ".env has no DATABASE_URL and none could be created." }
        $lines.Add("$k=$($Want[$k])")
        $added++
    }
    [IO.File]::WriteAllLines($Path, $lines, (New-Object Text.UTF8Encoding($false)))
    return $added
}

# ---------------------------------------------------------------------------
# Setup cache for rollback: <data>\updates\setup\F7FIVE0-Setup-<version>.exe.
# Setup copies itself there. Keep the installed version's copy and the newest
# one below it (the previous Setup); anything else goes. Never fatal.
# ---------------------------------------------------------------------------
function Prune-SetupCache([string]$CacheDir, [string]$InstalledVersion) {
    if (-not (Test-Path $CacheDir) -or -not (Test-SemVer $InstalledVersion)) { return }
    $copies = @()
    foreach ($f in Get-ChildItem $CacheDir -Filter "F7FIVE0-Setup-*.exe" -File -ErrorAction SilentlyContinue) {
        if ($f.Name -match '^F7FIVE0-Setup-(.+)\.exe$' -and (Test-SemVer $matches[1])) {
            $copies += [pscustomobject]@{ Version = $matches[1]; File = $f }
        }
    }
    $keep = @($InstalledVersion)
    $lower = @($copies | Where-Object { (Compare-SemVer $_.Version $InstalledVersion) -lt 0 })
    $previous = $null
    foreach ($c in $lower) {
        if ($null -eq $previous -or (Compare-SemVer $c.Version $previous.Version) -gt 0) { $previous = $c }
    }
    if ($previous) { $keep += $previous.Version }
    foreach ($c in $copies) {
        if ($keep -notcontains $c.Version) {
            Remove-Item -LiteralPath $c.File.FullName -Force -ErrorAction SilentlyContinue
            Info "removed cached Setup $($c.File.Name)"
        }
    }
}