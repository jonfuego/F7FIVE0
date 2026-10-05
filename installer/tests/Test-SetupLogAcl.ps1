# Test-SetupLogAcl.ps1
# Exercises Set-InstallAcl and the Setup-log Users grants against a throwaway
# install root, then asserts the resulting ACLs via icacls output:
#   - Users can read and list the logs\ folder (grant present, no (OI)/(CI))
#   - Users can read install-*.log and setup-summary.txt
#   - Users have no access on a service log (F7FIVE0-API.err.log)
# ACL changes only mean something when elevated, so when not elevated this
# prints "skipped: not elevated" and exits 0.
#
# Run: powershell -ExecutionPolicy Bypass -File installer\tests\Test-SetupLogAcl.ps1
# PowerShell 5.1 compatible, ASCII only.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "..\common.ps1")

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $elevated) {
    Write-Host "skipped: not elevated (ACL changes need elevation to be meaningful)"
    exit 0
}

$fails = 0
function Check([string]$name, [bool]$cond) {
    if ($cond) { Write-Host "PASS: $name" }
    else { Write-Host "FAIL: $name"; $script:fails++ }
}

$root = Join-Path $env:TEMP ("f7five0-acltest-" + [Guid]::NewGuid().ToString("N"))
Write-Host "Test root: $root"
try {
    New-Item -ItemType Directory -Path $root | Out-Null
    $logsDir = Join-Path $root "logs"
    New-Item -ItemType Directory -Path $logsDir | Out-Null

    $installLog  = Join-Path $logsDir "install-x.log"
    $summaryFile = Join-Path $logsDir "setup-summary.txt"
    $serviceLog  = Join-Path $logsDir "F7FIVE0-API.err.log"
    "install log" | Out-File -FilePath $installLog -Encoding ascii
    "summary"     | Out-File -FilePath $summaryFile -Encoding ascii
    "service err" | Out-File -FilePath $serviceLog -Encoding ascii

    # Lock the tree the way install.ps1 does (LocalSystem install: no service SID).
    Set-InstallAcl $root $null
    # Grant Users read on Setup's own files the way install.ps1 does.
    Grant-SetupLogRead $installLog
    Grant-SetupLogRead $summaryFile

    # --- logs folder: Users can list, no inheritance to children ---
    $folderAcl = (& icacls $logsDir) -join "`n"
    $usersLine = @(($folderAcl -split "`n") | Where-Object { $_ -match "BUILTIN\\Users" })
    $usersText = ($usersLine -join " ")
    Check "logs folder grants BUILTIN\Users" ($usersText -match "BUILTIN\\Users")
    Check "logs folder Users grant allows read/list (R)" ($usersText -match "\(R")
    Check "logs folder Users grant has no (OI)" (-not ($usersText -match "\(OI\)"))
    Check "logs folder Users grant has no (CI)" (-not ($usersText -match "\(CI\)"))

    # --- install log: Users can read ---
    $logAcl = (& icacls $installLog) -join "`n"
    Check "install log grants BUILTIN\Users read" (($logAcl -match "BUILTIN\\Users:") -and ($logAcl -match "BUILTIN\\Users:\(R\)"))

    # --- setup-summary.txt: Users can read ---
    $sumAcl = (& icacls $summaryFile) -join "`n"
    Check "setup-summary.txt grants BUILTIN\Users read" (($sumAcl -match "BUILTIN\\Users:") -and ($sumAcl -match "BUILTIN\\Users:\(R\)"))

    # --- service log: Users have NO access ---
    $svcAcl = (& icacls $serviceLog) -join "`n"
    Check "service err.log does not grant BUILTIN\Users" (-not ($svcAcl -match "BUILTIN\\Users"))

    # --- idempotent: re-run keeps it that way ---
    Set-InstallAcl $root $null
    Grant-SetupLogRead $installLog
    Grant-SetupLogRead $summaryFile
    $folderAcl2 = (& icacls $logsDir) -join "`n"
    $usersText2 = (@(($folderAcl2 -split "`n") | Where-Object { $_ -match "BUILTIN\\Users" }) -join " ")
    $logAcl2 = (& icacls $installLog) -join "`n"
    $svcAcl2 = (& icacls $serviceLog) -join "`n"
    Check "re-run: logs folder still lists for Users, no (OI)/(CI)" (($usersText2 -match "BUILTIN\\Users") -and -not ($usersText2 -match "\(OI\)") -and -not ($usersText2 -match "\(CI\)"))
    Check "re-run: install log still readable by Users" ($logAcl2 -match "BUILTIN\\Users:\(R\)")
    Check "re-run: service err.log still private" (-not ($svcAcl2 -match "BUILTIN\\Users"))
}
finally {
    try { & icacls $root /reset /T /C /Q | Out-Null } catch { }
    try { Remove-Item -Path $root -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}

if ($fails -gt 0) {
    Write-Host "RESULT: $fails check(s) failed"
    exit 1
}
Write-Host "RESULT: all checks passed"
exit 0
