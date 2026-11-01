# winget-line.ps1
# Offline test for Format-WingetLine (common.ps1): which winget output lines land
# in the Setup console and log. The 2026-10-21 clean-VM log had hundreds of
# progress-bar lines turned into mojibake and a spinner line per tick.
# The mojibake below is built from character codes so this file stays ASCII.
#
# Run: powershell -NoProfile -File installer\tests\winget-line.ps1
# PowerShell 5.1 compatible, ASCII only. Exit code 0 = pass.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "..\common.ps1")

$fails = 0
function Check([string]$name, [bool]$cond) {
    if ($cond) { Write-Host "PASS: $name" }
    else { Write-Host "FAIL: $name"; $script:fails++ }
}

# What the transcript showed for winget's bar: "full" and "empty" cells.
$full = [string][char]0x0393 + [char]0x00FB + [char]0x00EA
$empty = [string][char]0x0393 + [char]0x00FB + [char]0x00C6
$block = [string][char]0x2588
$shade = [string][char]0x2592

Check "mojibake bar with sizes is dropped" ((Format-WingetLine (($full * 8) + ($empty * 22) + "  1024 KB / 3.63 MB")) -eq "")
Check "mojibake bar with a percent is dropped" ((Format-WingetLine (($full * 2) + ($empty * 28) + "  7%")) -eq "")
Check "mojibake bar alone is dropped" ((Format-WingetLine ($empty * 30)) -eq "")
Check "real block bar is dropped" ((Format-WingetLine (($block * 10) + ($shade * 20) + "  25.7 MB / 25.7 MB")) -eq "")
Check "bare spinner is dropped" ((Format-WingetLine "  \  ") -eq "")
Check "blank is dropped" ((Format-WingetLine "   ") -eq "")
Check "spinner in front of a status is stripped" ((Format-WingetLine "- Cancelling operation") -eq "Cancelling operation")
Check "other spinner frames strip the same way" ((Format-WingetLine "| Cancelling operation") -eq "Cancelling operation")
Check "a normal line is kept as it is" ((Format-WingetLine "Found Python 3.12 [Python.Python.3.12] Version 3.12.10") -eq "Found Python 3.12 [Python.Python.3.12] Version 3.12.10")
Check "a line with a percent in words is kept" ((Format-WingetLine "Installer hash verified, 100% done") -eq "Installer hash verified, 100% done")

if ($fails -gt 0) { Write-Host "$fails check(s) failed"; exit 1 }
Write-Host "All winget-line checks passed"
exit 0
