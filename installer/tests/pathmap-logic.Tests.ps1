# Pester tests for installer\pathmap-logic.ps1: the decisions behind Setup's
# "map the drive letters your *arr apps use" step (a drive-letter root becomes a
# PATH_REWRITE_RULES entry in .env; a network folder needs nothing; a letter that
# is not a network drive is left alone; an *arr app that does not answer never
# fails the install).
#
# Works in Pester 3 and Pester 5 (Describe / It / Should Be only). Pester 5 runs a
# Describe body at discovery time only, so every It loads its own copy of the
# functions. Needs no admin rights, no network and no *arr app: every input is
# canned. Run: Invoke-Pester installer\tests\pathmap-logic.Tests.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

Describe "Drive letters and rules" {
    It "reads the drive letter of a path" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        Get-DriveLetterOfPath "N:\Movies" | Should Be "N:"
        Get-DriveLetterOfPath "n:/TV" | Should Be "N:"
        Get-DriveLetterOfPath "Z:" | Should Be "Z:"
        Get-DriveLetterOfPath "\\nas\share\Movies" | Should Be ""
        Get-DriveLetterOfPath "Movies\N:" | Should Be ""
        Get-DriveLetterOfPath "" | Should Be ""
    }
    It "knows a network path" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        (Test-UncPathText "\\nas\share") | Should Be $true
        (Test-UncPathText "\\nas\share\TV") | Should Be $true
        (Test-UncPathText "\\nas") | Should Be $false
        (Test-UncPathText "N:\Movies") | Should Be $false
    }
    It "reads and writes the rules text the backend reads" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $rules = @(ConvertFrom-RewriteRules "N:=\\nas\media; M:\=\\nas\music\ ;;bad;=x;y=")
        $rules.Count | Should Be 2
        $rules[0].Src | Should Be "N:"
        $rules[0].Dst | Should Be "\\nas\media"
        $rules[1].Src | Should Be "M:"
        $rules[1].Dst | Should Be "\\nas\music"
        ConvertTo-RewriteRules $rules | Should Be "N:=\\nas\media;M:=\\nas\music"
        @(ConvertFrom-RewriteRules "").Count | Should Be 0
    }
}

Describe "What each drive letter points at" {
    It "reads net use output" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $lines = @(
            "New connections will be remembered.",
            "",
            "Status       Local     Remote                    Network",
            "",
            "-------------------------------------------------------------------------------",
            "OK           N:        \\fuegonas\The Hive       Microsoft Windows Network",
            "Unavailable  Z:        \\nas\backup\             Microsoft Windows Network",
            "OK                     \\other\c$                Microsoft Windows Network",
            "The command completed successfully."
        )
        $map = ConvertFrom-NetUseLines $lines
        $map.Count | Should Be 2
        $map["N:"] | Should Be "\\fuegonas\The Hive"
        $map["Z:"] | Should Be "\\nas\backup"
    }
    It "combines the three sources, the first answer for a letter wins" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $smb = { @([pscustomobject]@{ LocalPath = "N:"; RemotePath = "\\smb\one" }) }
        $net = { @("OK           N:        \\net\one   Microsoft Windows Network", "OK           M:        \\net\two   Microsoft Windows Network") }
        $reg = { @([pscustomobject]@{ LocalPath = "M"; RemotePath = "\\reg\two" }, [pscustomobject]@{ LocalPath = "Q"; RemotePath = "\\reg\three" }) }
        $map = Get-NetworkDriveMap $smb $net $reg
        $map["N:"] | Should Be "\\smb\one"
        $map["M:"] | Should Be "\\net\two"
        $map["Q:"] | Should Be "\\reg\three"
    }
    It "still answers when the elevated login cannot see the mapping but the registry can" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $smb = { throw "no mappings in this session" }
        $net = { @("There are no entries in the list.") }
        $reg = { @([pscustomobject]@{ LocalPath = "N"; RemotePath = "\\fuegonas\The Hive" }) }
        (Get-NetworkDriveMap $smb $net $reg)["N:"] | Should Be "\\fuegonas\The Hive"
    }
    It "gives an empty map when nothing answers" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $map = Get-NetworkDriveMap { throw "x" } { throw "y" } { throw "z" }
        $map.Count | Should Be 0
    }
}

Describe "The plan" {
    It "resolves one drive-letter root and writes it" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $roots = @([pscustomobject]@{ App = "Radarr"; Path = "N:\Movies" })
        $plan = Get-PathMappingPlan $roots @{ "N:" = "\\nas\share" } ""
        $plan.Rules | Should Be "N:=\\nas\share"
        $plan.Changed | Should Be $true
        $plan.Added.Count | Should Be 1
        $plan.Added[0].Src | Should Be "N:"
        $plan.Added[0].Dst | Should Be "\\nas\share"
        $plan.Added[0].For | Should Be "Radarr folder N:\Movies"
    }
    It "ignores a network (UNC) root" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $roots = @([pscustomobject]@{ App = "Sonarr"; Path = "\\nas\share\TV" })
        $plan = Get-PathMappingPlan $roots @{ "N:" = "\\nas\share" } ""
        $plan.Rules | Should Be ""
        $plan.Changed | Should Be $false
        $plan.Added.Count | Should Be 0
        $plan.Skipped.Count | Should Be 0
    }
    It "keeps an existing rule and does not duplicate it" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $roots = @(
            [pscustomobject]@{ App = "Radarr"; Path = "N:\Movies" },
            [pscustomobject]@{ App = "Lidarr"; Path = "N:\Music" },
            [pscustomobject]@{ App = "Sonarr"; Path = "M:\TV" }
        )
        $map = @{ "N:" = "\\new\target"; "M:" = "\\nas\tv" }
        $plan = Get-PathMappingPlan $roots $map "N:=\\old\target;X:=\\keep\me"
        $plan.Rules | Should Be "N:=\\old\target;X:=\\keep\me;M:=\\nas\tv"
        $plan.Added.Count | Should Be 1
        $plan.Added[0].Src | Should Be "M:"
        @($plan.Kept).Count | Should Be 1
        $plan.Kept[0] | Should Be "N:"
    }
    It "writes one rule for a letter even when two apps use it" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $roots = @(
            [pscustomobject]@{ App = "Radarr"; Path = "N:\Movies" },
            [pscustomobject]@{ App = "Lidarr"; Path = "n:\Music" }
        )
        $plan = Get-PathMappingPlan $roots @{ "N:" = "\\nas\share" } ""
        $plan.Rules | Should Be "N:=\\nas\share"
        $plan.Added.Count | Should Be 1
    }
    It "leaves an unresolvable letter alone and says why" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $roots = @([pscustomobject]@{ App = "Lidarr"; Path = "D:\Music" })
        $plan = Get-PathMappingPlan $roots @{ "N:" = "\\nas\share" } ""
        $plan.Rules | Should Be ""
        $plan.Changed | Should Be $false
        $plan.Added.Count | Should Be 0
        $plan.Skipped.Count | Should Be 1
        ($plan.Skipped[0] -like "Lidarr uses D:\Music, but D: is not a network drive*") | Should Be $true
    }
}

Describe "The step" {
    It "writes a mapping for a drive-letter root and says so in the log" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $log = New-Object System.Collections.Generic.List[string]
        $apps = @([pscustomobject]@{ Name = "Radarr"; Url = "http://127.0.0.1:7878"; Key = "k" })
        $fetch = { param($app) @("N:\Movies", "\\nas\share\TV") }
        $plan = Invoke-PathMappingStep $apps "" @{ "N:" = "\\nas\share" } $fetch { param($l) $log.Add($l) }
        $plan.Rules | Should Be "N:=\\nas\share"
        $plan.Asked | Should Be 1
        ($log -contains "Mapped N: to \\nas\share (for Radarr folder N:\Movies).") | Should Be $true
    }
    It "writes nothing and carries on when the *arr app does not answer" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $log = New-Object System.Collections.Generic.List[string]
        $apps = @([pscustomobject]@{ Name = "Radarr"; Url = "http://127.0.0.1:7878"; Key = "k" })
        $fetch = { param($app) throw "Unable to connect to the remote server" }
        $plan = Invoke-PathMappingStep $apps "X:=\\keep\me" @{ "N:" = "\\nas\share" } $fetch { param($l) $log.Add($l) }
        $plan.Changed | Should Be $false
        $plan.Rules | Should Be "X:=\\keep\me"
        $plan.Asked | Should Be 0
        ($log[0] -like "Radarr did not answer (Unable to connect to the remote server)*") | Should Be $true
    }
    It "still asks the other apps when one does not answer" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $apps = @(
            [pscustomobject]@{ Name = "Radarr"; Url = "u"; Key = "k" },
            [pscustomobject]@{ Name = "Lidarr"; Url = "u"; Key = "k" }
        )
        $fetch = { param($app) if ($app.Name -eq "Radarr") { throw "down" } else { @("M:\Music") } }
        $plan = Invoke-PathMappingStep $apps "" @{ "M:" = "\\nas\music" } $fetch { param($l) }
        $plan.Rules | Should Be "M:=\\nas\music"
        $plan.Asked | Should Be 1
    }
    It "does not throw when the log itself fails" {
        . (Join-Path $PSScriptRoot "..\pathmap-logic.ps1")
        $apps = @([pscustomobject]@{ Name = "Radarr"; Url = "u"; Key = "k" })
        $plan = Invoke-PathMappingStep $apps "" @{} { param($app) @("D:\x") } { param($l) throw "log is closed" }
        $plan.Changed | Should Be $false
    }
}

Describe "Wiring" {
    It "install.ps1 runs the step, saves the rule and lists each mapping in the summary" {
        $install = Get-Content -Raw -Path (Join-Path $PSScriptRoot "..\install.ps1")
        $install | Should Match 'pathmap-logic\.ps1'
        $install | Should Match 'Invoke-PathMappingStep'
        $install | Should Match 'Set-EnvKey "PATH_REWRITE_RULES"'
        $install | Should Match 'PathMappingsWritten\.Add'
        $install | Should Match 'Network drives mapped for the services'
        $install | Should Match 'setup-summary\.txt'
    }
    It "build-dist.ps1 ships pathmap-logic.ps1" {
        $dist = Get-Content -Raw -Path (Join-Path $PSScriptRoot "..\build-dist.ps1")
        $dist | Should Match 'pathmap-logic\.ps1'
    }
    It "pathmap-logic.ps1 is plain ASCII, so Windows PowerShell 5.1 reads it" {
        $bytes = [IO.File]::ReadAllBytes((Join-Path $PSScriptRoot "..\pathmap-logic.ps1"))
        (@($bytes | Where-Object { $_ -gt 127 })).Count | Should Be 0
    }
}
