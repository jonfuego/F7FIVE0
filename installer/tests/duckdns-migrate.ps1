# duckdns-migrate.ps1
# Offline test for Get-DuckDnsFromTaskArgs (common.ps1), the parser Setup uses to
# move the DuckDNS domain and token out of the old F7FIVE0-DuckDNS scheduled
# task and into .env. No network, no scheduled task, no .env: pure string work.
# The tokens below are fake on purpose.
#
# Run: powershell -NoProfile -File installer\tests\duckdns-migrate.ps1
# PowerShell 5.1 compatible, ASCII only. Exit code 0 = pass.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "..\common.ps1")

$fails = 0
function Check([string]$name, [bool]$cond) {
    if ($cond) { Write-Host "PASS: $name" }
    else { Write-Host "FAIL: $name"; $script:fails++ }
}

$fakeToken = "aaaaaaaa-0000-0000-0000-000000000000"

# The exact shape the old remote-access.ps1 registered.
$good = "-NoProfile -WindowStyle Hidden -Command `"Invoke-RestMethod -UseBasicParsing 'https://www.duckdns.org/update?domains=examplehome&token=$fakeToken&ip=' | Out-Null`""
$r = Get-DuckDnsFromTaskArgs $good
Check "good arguments: parsed" ($null -ne $r)
Check "good arguments: domain" ($r.Domain -eq "examplehome")
Check "good arguments: token" ($r.Token -eq $fakeToken)

$upper = Get-DuckDnsFromTaskArgs ("domains=ExampleHome&token=" + $fakeToken.ToUpper() + "&ip=")
Check "upper case is folded to lower case" ($upper -and $upper.Domain -eq "examplehome" -and $upper.Token -eq $fakeToken)

$short = Get-DuckDnsFromTaskArgs "domains=examplehome&token=not-a-real-token&ip="
Check "wrong token shape: null" ($null -eq $short)

$inject = Get-DuckDnsFromTaskArgs "domains=examplehome&token=$fakeToken'; calc; '&ip="
Check "token followed by junk still parses only the token" ($inject -and $inject.Token -eq $fakeToken)

$noDomain = Get-DuckDnsFromTaskArgs "-Command `"Invoke-RestMethod 'https://www.duckdns.org/update?token=$fakeToken&ip='`""
Check "missing domain: null" ($null -eq $noDomain)

$emptyDomain = Get-DuckDnsFromTaskArgs "domains=&token=$fakeToken&ip="
Check "empty domain: null" ($null -eq $emptyDomain)

Check "empty text: null" ($null -eq (Get-DuckDnsFromTaskArgs ""))
Check "null text: null" ($null -eq (Get-DuckDnsFromTaskArgs $null))
Check "unrelated task arguments: null" ($null -eq (Get-DuckDnsFromTaskArgs "-NoProfile -File C:\other.ps1"))

# $DuckPattern is shared with remote-access.ps1.
Check "DuckPattern accepts a token" ($fakeToken -match $DuckPattern)
Check "DuckPattern rejects a bad token" ("hello" -notmatch $DuckPattern)

if ($fails -gt 0) { Write-Host "$fails check(s) failed"; exit 1 }
Write-Host "all checks passed"
exit 0
