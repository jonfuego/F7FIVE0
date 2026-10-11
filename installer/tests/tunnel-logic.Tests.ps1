# Pester tests for installer\tunnel-logic.ps1: the pure decisions behind the
# Cloudflare tunnel step of remote-access.ps1 (one tunnel per install, never
# join a tunnel that is running elsewhere, check where the DNS record points).
#
# Works in Pester 3 and Pester 5 (Describe / It / Should Be only). Pester 5
# runs a Describe body at discovery time only, so every It loads its own copy of
# the functions and canned text from tunnel-test-setup.ps1. Needs no
# admin rights, no network, no cloudflared: every input is canned text.
# Run: Invoke-Pester installer\tests\tunnel-logic.Tests.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

Describe "Tunnel name" {
    It "is f7five0- plus the computer name, lowercased" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ConvertTo-TunnelName "MEDIABOX" | Should Be "f7five0-mediabox"
    }
    It "keeps letters, digits and hyphens" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ConvertTo-TunnelName "F7-Main-01" | Should Be "f7five0-f7-main-01"
    }
    It "collapses other characters into one hyphen and trims hyphens" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ConvertTo-TunnelName "  My PC__Upstairs!! " | Should Be "f7five0-my-pc-upstairs"
    }
    It "falls back to pc when nothing usable is left" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ConvertTo-TunnelName "" | Should Be "f7five0-pc"
        ConvertTo-TunnelName "!!!" | Should Be "f7five0-pc"
    }
    It "keeps a long computer name short and never ends in a hyphen" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $long = ("a" * 39) + "-" + ("b" * 30)
        $n = ConvertTo-TunnelName $long
        ($n.Length -le ("f7five0-".Length + 40)) | Should Be $true
        ($n -match '-$') | Should Be $false
    }
    It "only ever produces letters, digits and hyphens" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        foreach ($c in @("DESKTOP-9K2L", "jon's pc", "Server.One", "caf", "A B C")) {
            (ConvertTo-TunnelName $c) -match '^[a-z0-9]+(-[a-z0-9]+)*$' | Should Be $true
        }
    }
    It "gives two computers two different tunnels" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ((ConvertTo-TunnelName "MAINPC") -eq (ConvertTo-TunnelName "TESTVM")) | Should Be $false
    }
    It "accepts the names Jon made by hand and rejects junk" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        Test-TunnelNameValid "f7-main" | Should Be $true
        Test-TunnelNameValid "f750" | Should Be $true
        Test-TunnelNameValid "has space" | Should Be $false
        Test-TunnelNameValid "-lead" | Should Be $false
        Test-TunnelNameValid "" | Should Be $false
    }
}

Describe "Tunnel name decision (keep what the install has)" {
    It "gives a brand new install its own per-computer name" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "" "" "MAINPC"
        $d.Name | Should Be "f7five0-mainpc"
        $d.Source | Should Be "new"
        ($d.Reason -match "own name") | Should Be $true
    }
    It "never falls back to the shared name f7five0" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "" "" "TESTVM"
        ($d.Name -eq "f7five0") | Should Be $false
    }
    It "reuses the name saved in .env" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "f7five0-mainpc" "" "RENAMEDPC"
        $d.Name | Should Be "f7five0-mainpc"
        $d.Source | Should Be "saved"
    }
    It "keeps the saved name even when the computer was renamed" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Get-TunnelNameDecision "f7five0-oldname" "" "NEWNAME").Name | Should Be "f7five0-oldname"
    }
    It "keeps a hand-made tunnel the install already runs (main PC f7-main)" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "" "f7-main" "MAINPC"
        $d.Name | Should Be "f7-main"
        $d.Source | Should Be "existing"
        ($d.Reason -match "keeping it") | Should Be $true
    }
    It "keeps a hand-made tunnel the install already runs (test VM f750)" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "" "f750" "TESTVM"
        $d.Name | Should Be "f750"
        $d.Source | Should Be "existing"
    }
    It "lets the saved name win over a different tunnel found locally" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "f7five0-mainpc" "f7-main" "MAINPC"
        $d.Name | Should Be "f7five0-mainpc"
        $d.Source | Should Be "saved"
    }
    It "ignores a saved name Cloudflare could not use and says so" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $d = Get-TunnelNameDecision "bad name!" "f750" "TESTVM"
        $d.Name | Should Be "f750"
        ($d.Reason -match "bad name!") | Should Be $true
    }
    It "is the same answer on every rerun" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $first = Get-TunnelNameDecision "" "" "MAINPC"
        $second = Get-TunnelNameDecision $first.Name "" "MAINPC"
        $second.Name | Should Be $first.Name
    }
}

Describe "What this install already runs" {
    It "reads the tunnel and credentials file from Setup's config.yml" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $cfg = "# Written by F7FIVE0 setup.`r`ntunnel: bf74c62c-1111-4222-8333-444455556666`r`ncredentials-file: C:\F7FIVE0\cloudflared\tunnel.json`r`ningress:`r`n  - hostname: media.fuegofam.com`r`n    service: http://127.0.0.1:3001`r`n  - service: http_status:404`r`n"
        $l = Read-LocalTunnel $cfg ""
        $l.Ref | Should Be "bf74c62c-1111-4222-8333-444455556666"
        $l.CredFile | Should Be "C:\F7FIVE0\cloudflared\tunnel.json"
    }
    It "reads a tunnel named by name in a hand-made config" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $l = Read-LocalTunnel "tunnel: f750`ncredentials-file: 'C:\creds\f750.json'`n" ""
        $l.Ref | Should Be "f750"
        $l.CredFile | Should Be "C:\creds\f750.json"
    }
    It "falls back to the TunnelID in tunnel.json when there is no config" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $cred = '{"AccountTag":"a","TunnelSecret":"s","TunnelID":"BF74C62C-1111-4222-8333-444455556666"}'
        (Read-LocalTunnel "" $cred).Ref | Should Be "bf74c62c-1111-4222-8333-444455556666"
    }
    It "finds nothing on a brand new install" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $l = Read-LocalTunnel "" ""
        $l.Ref | Should Be ""
        $l.CredFile | Should Be ""
    }
    It "copes with unreadable credentials" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        Get-CredTunnelId "not json at all" | Should Be ""
    }
}

Describe "Connector check before fetching credentials" {
    It "stops when the tunnel has active connectors" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $u = Get-TunnelUseDecision $twoConnectors "f7five0" $false
        $u.InUse | Should Be $true
        $u.State | Should Be "active"
        $u.Count | Should Be 2
    }
    It "says which tunnel, that it is in use elsewhere, and what to do" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $m = (Get-TunnelUseDecision $twoConnectors "f7five0" $false).Message
        ($m -match "'f7five0'") | Should Be $true
        ($m -match "already in use elsewhere") | Should Be $true
        ($m -match "CLOUDFLARE_TUNNEL_NAME") | Should Be $true
        ($m -match "Pick another name") | Should Be $true
    }
    It "goes ahead when the tunnel has no active connection" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $u = Get-TunnelUseDecision $none "f7five0-testvm" $false
        $u.InUse | Should Be $false
        $u.State | Should Be "none"
        $u.Message | Should Be ""
    }
    It "goes ahead when the connectors are this machine's own service" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $u = Get-TunnelUseDecision $twoConnectors "f7-main" $true
        $u.InUse | Should Be $false
        $u.State | Should Be "active"
    }
    It "treats the connector header with no rows as connectors (evidence, fail safe)" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $u = Get-TunnelUseDecision "NAME: x`nCONNECTOR ID   CREATED   ARCHITECTURE" "x" $false
        $u.InUse | Should Be $true
    }
    It "reads --output json with connectors" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $json = '{"id":"431c14c2-1111-4222-8333-444455556666","name":"f7five0","connectors":[{"id":"5e1a7e0c-2a1b-4c3d-9e8f-0a1b2c3d4e5f","conns":[{"colo_name":"bos01"}]}]}'
        $u = Get-TunnelUseDecision $json "f7five0" $false
        $u.InUse | Should Be $true
        $u.Count | Should Be 1
    }
    It "reads --output json with an empty connector list" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $json = '{"id":"431c14c2-1111-4222-8333-444455556666","name":"f7five0","connectors":[]}'
        (Get-TunnelUseDecision $json "f7five0" $false).InUse | Should Be $false
    }
    It "does not call it in use on output with no sign of connectors, and says it could not tell" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $u = Get-TunnelUseDecision "error: something unexpected happened" "x" $false
        $u.InUse | Should Be $false
        $u.State | Should Be "unknown"
        ($u.Note -match "Could not tell") | Should Be $true
    }
    It "does not call it in use on empty output" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Get-TunnelUseDecision "" "x" $false).InUse | Should Be $false
    }
}

Describe "Where the DNS record points after route dns" {
    It "sees an old tunnel in 'already configured to route to your tunnel'" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $r = Test-RouteDnsOutput "2026-10-11T15:00:00Z INF f750.fuegofam.com is already configured to route to your tunnel tunnelID=$other" $ours
        $r.State | Should Be "other"
        $r.OtherId | Should Be $other
    }
    It "sees a shortened old tunnel id (431c14c2) as another tunnel" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $r = Test-RouteDnsOutput "f750.fuegofam.com is already configured to route to your tunnel 431c14c2" $ours
        $r.State | Should Be "other"
        $r.OtherId | Should Be "431c14c2"
    }
    It "accepts 'already configured' when the tunnel is ours" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Test-RouteDnsOutput "x.example.com is already configured to route to your tunnel tunnelID=$ours" $ours).State | Should Be "ours"
    }
    It "accepts a new record for our tunnel" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Test-RouteDnsOutput "Added CNAME x.example.com which will route to this tunnel tunnelID=$ours" $ours).State | Should Be "ours"
    }
    It "does not guess from other output" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Test-RouteDnsOutput "something else" $ours).State | Should Be "unknown"
        (Test-RouteDnsOutput "" $ours).State | Should Be "unknown"
    }
    It "matches a CNAME target to this tunnel (case and trailing dot ignored)" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Compare-CnameTarget "$ours.cfargotunnel.com" $ours).State | Should Be "match"
        (Compare-CnameTarget "$($ours.ToUpper()).CFARGOTUNNEL.COM." $ours).State | Should Be "match"
    }
    It "spots a CNAME on another tunnel" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $c = Compare-CnameTarget "$other.cfargotunnel.com" $ours
        $c.State | Should Be "other"
        $c.OtherId | Should Be $other
    }
    It "spots a CNAME that is not a tunnel at all" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Compare-CnameTarget "somewhere.example.net" $ours).State | Should Be "foreign"
    }
    It "reports a missing CNAME" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Compare-CnameTarget "" $ours).State | Should Be "missing"
        (Compare-CnameTarget $null $ours).State | Should Be "missing"
    }
    It "fails loudly when cloudflared left the record on another tunnel, even with exit code 0" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $v = Get-RouteDnsVerdict "f750.fuegofam.com is already configured to route to your tunnel tunnelID=$other" $ours "" "f750.fuegofam.com"
        $v.State | Should Be "failed"
        ($v.Message -match "f750.fuegofam.com") | Should Be $true
        ($v.Message -match $other) | Should Be $true
        ($v.Message -match "not started") | Should Be $true
    }
    It "fails when the lookup shows another tunnel and allows a retry for DNS delay" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $v = Get-RouteDnsVerdict "Added CNAME x.example.com which will route to this tunnel tunnelID=$ours" $ours "$other.cfargotunnel.com" "x.example.com"
        $v.State | Should Be "failed"
        $v.Retryable | Should Be $true
    }
    It "fails when the lookup shows a non-tunnel target" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Get-RouteDnsVerdict "" $ours "old.example.net" "x.example.com").State | Should Be "failed"
    }
    It "passes when the lookup shows this tunnel" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Get-RouteDnsVerdict "" $ours "$ours.cfargotunnel.com" "x.example.com").State | Should Be "ok"
    }
    It "passes on cloudflared's own word when a proxied record hides its CNAME" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Get-RouteDnsVerdict "Added CNAME x.example.com which will route to this tunnel tunnelID=$ours" $ours "" "x.example.com").State | Should Be "ok"
    }
    It "reports unknown, not ok, when nothing can confirm it" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $v = Get-RouteDnsVerdict "" $ours "" "x.example.com"
        $v.State | Should Be "unknown"
        ($v.Message -match "Could not confirm") | Should Be $true
    }
    It "treats a shortened id as the same tunnel only with 8 or more characters" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        Test-SameTunnelId "431c14c2" "431c14c2-aaaa-4bbb-8ccc-ddddeeeeffff" | Should Be $true
        Test-SameTunnelId "431c14" "431c14c2-aaaa-4bbb-8ccc-ddddeeeeffff" | Should Be $false
        Test-SameTunnelId "" "" | Should Be $false
    }
}

Describe "Cloudflare login certificate" {
    It "reads the zone and API token cloudflared saved" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $json = '{"zoneID":"zone123","accountID":"acct456","apiToken":"tok789"}'
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
        $pem = "-----BEGIN ARGO TUNNEL TOKEN-----`n$b64`n-----END ARGO TUNNEL TOKEN-----`n"
        $t = Read-OriginCertToken $pem
        $t.ZoneId | Should Be "zone123"
        $t.AccountId | Should Be "acct456"
        $t.ApiToken | Should Be "tok789"
    }
    It "returns nothing for text that is not a login certificate" {
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        (Read-OriginCertToken "hello") -eq $null | Should Be $true
        (Read-OriginCertToken "-----BEGIN ARGO TUNNEL TOKEN-----`n!!!`n-----END ARGO TUNNEL TOKEN-----") -eq $null | Should Be $true
    }
}

Describe "remote-access.ps1 uses the decisions" {
    It "has no fixed tunnel name left" {
        $loadScripts = $true
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ($ra -match '\$name\s*=\s*"f7five0"') | Should Be $false
    }
    It "names the tunnel through the decision function and saves it to .env" {
        $loadScripts = $true
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ($ra -match 'Get-TunnelNameDecision') | Should Be $true
        ($ra -match 'Set-EnvKey "CLOUDFLARE_TUNNEL_NAME"') | Should Be $true
    }
    It "checks for connectors before it fetches credentials" {
        $loadScripts = $true
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $i = $ra.IndexOf("Get-TunnelUseDecision")
        $j = $ra.IndexOf("token --cred-file")
        ($i -gt 0 -and $j -gt $i) | Should Be $true
    }
    It "verifies the DNS record after route dns, before the service is written" {
        $loadScripts = $true
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        $r = $ra.IndexOf("route dns --overwrite-dns")
        $c = $ra.IndexOf("Confirm-TunnelDns", $r)
        $s = $ra.IndexOf('Install-Svc "F7FIVE0-Tunnel" $cfd "tunnel --no-autoupdate --config')
        ($r -gt 0 -and $c -gt $r -and $s -gt $c) | Should Be $true
    }
    It "is dot-sourced from remote-access.ps1 and shipped by build-dist.ps1" {
        $loadScripts = $true
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        ($ra -match 'tunnel-logic\.ps1') | Should Be $true
        ($dist -match '"tunnel-logic\.ps1"') | Should Be $true
    }
    It "keeps the new files ASCII only" {
        $loadScripts = $true
        . (Join-Path $PSScriptRoot "tunnel-test-setup.ps1")
        foreach ($f in @("..\tunnel-logic.ps1", "..\remote-access.ps1", "tunnel-logic.Tests.ps1", "tunnel-test-setup.ps1")) {
            $bytes = [IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $f))
            @($bytes | Where-Object { $_ -gt 127 }).Count | Should Be 0
        }
    }
}
