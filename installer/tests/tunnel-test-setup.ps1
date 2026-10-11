# Loaded by every It in tunnel-logic.Tests.ps1 (dot-sourced, so the functions
# and the canned text below land in that It's scope). Pester 3 and 5 both work.
# Not a test file itself. Windows PowerShell 5.1 compatible, ASCII only.

. (Join-Path $PSScriptRoot "..\tunnel-logic.ps1")

# Real-looking `cloudflared tunnel info` output.
$twoConnectors = @(
    "NAME:     f7five0",
    "ID:       431c14c2-1111-4222-8333-444455556666",
    "CREATED:  2026-01-02 03:04:05.678901 +0000 UTC",
    "",
    "CONNECTOR ID                         CREATED              ARCHITECTURE VERSION  ORIGIN IP    EDGE",
    "5e1a7e0c-2a1b-4c3d-9e8f-0a1b2c3d4e5f 2026-10-11T14:05:00Z windows_amd64 2026.9.1 203.0.113.10 1xbos01, 1xbos06",
    "9b8c7d6e-5f4a-4b3c-8d2e-1f0a9b8c7d6e 2026-10-11T14:06:30Z windows_amd64 2026.9.1 203.0.113.11 2xewr01"
) -join "`n"
$none = "Your tunnel 431c14c2-1111-4222-8333-444455556666 does not have any active connection."

# Tunnel ids for the DNS tests.
$ours = "bf74c62c-1111-4222-8333-444455556666"
$other = "431c14c2-aaaa-4bbb-8ccc-ddddeeeeffff"

# The scripts under test, as text (only when the It sets $loadScripts first).
if ($loadScripts) {
    $ra = Get-Content -Raw -Path (Join-Path $PSScriptRoot "..\remote-access.ps1")
    $dist = Get-Content -Raw -Path (Join-Path $PSScriptRoot "..\build-dist.ps1")
}
