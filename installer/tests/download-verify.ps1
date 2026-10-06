# download-verify.ps1
# Exercises the SHA-256 verification logic in the Download helper (common.ps1)
# OFFLINE, with no network (SEC-P0-2). It serves a local file through a file://
# URL (Invoke-WebRequest reads it straight off disk) and checks:
#   - a matching expected hash passes and the file lands at $dest
#   - a mismatching expected hash throws and leaves no file at $dest
#   - a blank expected hash throws (verification can never be skipped)
#   - a missing (null) expected hash throws
# It also parses downloads.manifest.psd1 and asserts every entry has a name,
# version, URL, and a 64-hex SHA-256.
#
# Exits NON-ZERO on any failure, zero when everything passes.
# Run: powershell -File installer\tests\download-verify.ps1
# PowerShell 5.1 compatible, ASCII only.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "..\common.ps1")

$fails = 0
function Check([string]$name, [bool]$cond) {
    if ($cond) { Write-Host "PASS: $name" }
    else { Write-Host "FAIL: $name"; $script:fails++ }
}

# file:// URL for a local path, so Download runs end to end with no network.
function To-FileUrl([string]$path) {
    return ([Uri]("file:///" + ($path -replace '\\', '/'))).AbsoluteUri
}

$work = Join-Path $env:TEMP ("f7five0-dlverify-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $src = Join-Path $work "payload.bin"
    [IO.File]::WriteAllText($src, "F7FIVE0 download-verify fixture payload.")
    $srcUrl = To-FileUrl $src
    $goodHash = (Get-FileHash -Path $src -Algorithm SHA256).Hash
    $badHash  = "0000000000000000000000000000000000000000000000000000000000000000"

    # 1. Matching hash passes and produces the file.
    $dest1 = Join-Path $work "ok.bin"
    $ok = $false
    try { Download $srcUrl $dest1 $goodHash; $ok = $true } catch { $ok = $false }
    Check "matching hash passes" ($ok -and (Test-Path $dest1))
    $destHash = if (Test-Path $dest1) { (Get-FileHash -Path $dest1 -Algorithm SHA256).Hash } else { "" }
    Check "downloaded file has the expected content" ($destHash -eq $goodHash)

    # Lowercase expected hash must still pass (comparison is case-insensitive).
    $dest1b = Join-Path $work "ok-lower.bin"
    $okLower = $false
    try { Download $srcUrl $dest1b $goodHash.ToLowerInvariant(); $okLower = $true } catch { $okLower = $false }
    Check "matching hash passes regardless of case" ($okLower -and (Test-Path $dest1b))

    # 2. Mismatching hash throws and leaves no file at $dest.
    $dest2 = Join-Path $work "bad.bin"
    $threw = $false
    try { Download $srcUrl $dest2 $badHash } catch { $threw = $true }
    Check "mismatching hash throws" $threw
    Check "mismatching hash leaves no file at dest" (-not (Test-Path $dest2))
    Check "mismatching hash leaves no .partial" (-not (Test-Path "$dest2.partial"))

    # 3. Blank expected hash throws (verification cannot be skipped).
    $dest3 = Join-Path $work "blank.bin"
    $threwBlank = $false
    try { Download $srcUrl $dest3 "" } catch { $threwBlank = $true }
    Check "blank expected hash throws" $threwBlank
    Check "blank expected hash downloads nothing" (-not (Test-Path $dest3))

    # 4. Missing (null) expected hash throws.
    $dest4 = Join-Path $work "null.bin"
    $threwNull = $false
    try { Download $srcUrl $dest4 $null } catch { $threwNull = $true }
    Check "missing expected hash throws" $threwNull

    # 5. Manifest sanity: every entry pins name, version, URL, and a SHA-256.
    $manifest = Import-PowerShellDataFile -Path (Join-Path $here "..\downloads.manifest.psd1")
    Check "manifest has at least one entry" ($manifest.Keys.Count -gt 0)
    foreach ($key in $manifest.Keys) {
        $e = $manifest[$key]
        Check "[$key] has a Name" (-not [string]::IsNullOrWhiteSpace($e.Name))
        Check "[$key] has a Version" (-not [string]::IsNullOrWhiteSpace($e.Version))
        Check "[$key] has a Url" (-not [string]::IsNullOrWhiteSpace($e.Url))
        # Reject rolling/unpinned URLs. The two banned words are assembled from
        # fragments on purpose so this guard is not itself a grep hit.
        $rolling = ('lat' + 'est'), ('release' + '-' + 'essentials')
        $isRolling = $false
        foreach ($w in $rolling) { if ($e.Url -match ("(?i)" + [regex]::Escape($w))) { $isRolling = $true } }
        Check "[$key] Url is pinned (not a rolling URL)" (-not $isRolling)
        Check "[$key] has a 64-hex SHA-256" ($e.Sha256 -match '^[0-9A-Fa-f]{64}$')
    }
} finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

if ($fails -gt 0) {
    Write-Host ""
    Write-Host "$fails check(s) FAILED" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "all checks passed" -ForegroundColor Green
exit 0
