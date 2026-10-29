# Pester tests for how Setup tells a new install from an upgrade
# (Test-CompletedInstall, Write-InstallComplete and Get-DbUrlPassword in
# common.ps1, and the matching IsUpgrade in F7FIVE0.iss).
#
# Hand test I-11: a first install stopped after PostgreSQL went in had already
# written .env, and the rerun took .env as "upgrade": no admin page, no admin
# account, nobody could sign in. An upgrade now needs a completed install: the
# data\install-complete.json marker, or (installs from before the marker) the
# F7FIVE0-API service.
#
# Works in Pester 3 and Pester 5 (Describe / BeforeAll / It / Should Be only);
# every It loads its own copy of the common.ps1 functions. No admin rights, no
# services, no database.
# Run: Invoke-Pester installer\tests\upgrade-detect.Tests.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

Describe "Test-CompletedInstall" {
    BeforeAll {
        function New-FakeInstall([string]$name, [bool]$withEnv, [bool]$marker) {
            $root = Join-Path ([IO.Path]::GetTempPath()) ("f7-upgrade-detect-" + $name + "-" + [guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path (Join-Path $root "data") -Force | Out-Null
            if ($withEnv) { Set-Content -Path (Join-Path $root ".env") -Value "DATABASE_URL=postgresql+psycopg://f7five0:abc@127.0.0.1:5432/f7five0" -Encoding ASCII }
            if ($marker) { Set-Content -Path (Join-Path $root "data\install-complete.json") -Value "{}" -Encoding ASCII }
            return $root
        }
    }
    It "is a new install when there is no .env" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = New-FakeInstall "none" $false $false
        try {
            (Test-CompletedInstall $root $false) | Should Be $false
            # A leftover service without .env is not an install to upgrade.
            (Test-CompletedInstall $root $true) | Should Be $false
        } finally { Remove-Item -Recurse -Force $root }
    }
    It "is a new install when a first install stopped after writing .env (I-11)" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = New-FakeInstall "stopped" $true $false
        try {
            (Test-CompletedInstall $root $false) | Should Be $false
        } finally { Remove-Item -Recurse -Force $root }
    }
    It "is an upgrade when the install finished (marker)" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = New-FakeInstall "done" $true $true
        try {
            (Test-CompletedInstall $root $false) | Should Be $true
            (Test-CompletedInstall $root $true) | Should Be $true
        } finally { Remove-Item -Recurse -Force $root }
    }
    It "is an upgrade for an install from before the marker (service registered)" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = New-FakeInstall "old" $true $false
        try {
            (Test-CompletedInstall $root $true) | Should Be $true
        } finally { Remove-Item -Recurse -Force $root }
    }
    It "a marker without .env is still a new install (data kept, settings deleted)" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = New-FakeInstall "markeronly" $false $true
        try {
            (Test-CompletedInstall $root $false) | Should Be $false
        } finally { Remove-Item -Recurse -Force $root }
    }
    It "Write-InstallComplete makes the next run an upgrade" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = New-FakeInstall "write" $true $false
        try {
            (Test-CompletedInstall $root $false) | Should Be $false
            Write-InstallComplete $root "1.0.19"
            (Test-CompletedInstall $root $false) | Should Be $true
            $rec = Get-Content (Join-Path $root "data\install-complete.json") -Raw | ConvertFrom-Json
            $rec.version | Should Be "1.0.19"
            ($rec.completed_at -match '^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$') | Should Be $true
            # Blank version (a git checkout run) still marks the install complete.
            Write-InstallComplete $root ""
            (Test-CompletedInstall $root $false) | Should Be $true
        } finally { Remove-Item -Recurse -Force $root }
    }
}

Describe "Get-DbUrlPassword" {
    It "reads the password Setup wrote" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        Get-DbUrlPassword "postgresql+psycopg://f7five0:Ab-c_9xYz@127.0.0.1:5432/f7five0" "f7five0" | Should Be "Ab-c_9xYz"
        Get-DbUrlPassword "postgresql://f7five0:pw@localhost/f7five0" "f7five0" | Should Be "pw"
        Get-DbUrlPassword "`"postgresql+psycopg://f7five0:pw@127.0.0.1:5432/f7five0`"" "f7five0" | Should Be "pw"
    }
    It "decodes a percent-encoded password" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        Get-DbUrlPassword "postgresql+psycopg://f7five0:a%40b%27c@127.0.0.1:5432/f7five0" "f7five0" | Should Be "a@b'c"
    }
    It "gives nothing for a blank URL, another user, or no password" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        Get-DbUrlPassword "" "f7five0" | Should Be ""
        Get-DbUrlPassword "postgresql+psycopg://other:pw@127.0.0.1:5432/f7five0" "f7five0" | Should Be ""
        Get-DbUrlPassword "postgresql+psycopg://f7five0@127.0.0.1:5432/f7five0" "f7five0" | Should Be ""
        Get-DbUrlPassword "sqlite:///f7five0.db" "f7five0" | Should Be ""
    }
}

Describe "install.ps1 and F7FIVE0.iss use the same test" {
    It "install.ps1 decides IsUpgrade with Test-CompletedInstall, not .env alone" {
        $src = Get-Content (Join-Path $PSScriptRoot "..\install.ps1") -Raw
        ($src -match '\$IsUpgrade\s*=\s*Test-CompletedInstall \$InstallDir') | Should Be $true
        ($src -match '\$IsUpgrade\s*=\s*Test-Path \$EnvFile') | Should Be $false
        ($src -match 'Get-Service -Name "F7FIVE0-API"') | Should Be $true
    }
    It "install.ps1 writes the marker as the last step of a successful run" {
        $src = Get-Content (Join-Path $PSScriptRoot "..\install.ps1") -Raw
        $write = $src.IndexOf('Write-InstallComplete $InstallDir')
        $summary = $src.IndexOf('Grant-SetupLogRead $summaryFile')
        $catch = $src.LastIndexOf('} catch {')
        ($write -gt $summary) | Should Be $true
        ($write -lt $catch) | Should Be $true
    }
    It "install.ps1 keeps the database password .env already has" {
        $src = Get-Content (Join-Path $PSScriptRoot "..\install.ps1") -Raw
        ($src -match 'Get-DbUrlPassword \(Get-EnvValue "DATABASE_URL"\) \$DbUser') | Should Be $true
    }
    It "F7FIVE0.iss IsUpgrade checks the same marker and service" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $iss = Get-Content (Join-Path $PSScriptRoot "..\F7FIVE0.iss") -Raw
        $m = [regex]::Match($iss, '(?s)function IsUpgrade: Boolean;.*?\nend;')
        $m.Success | Should Be $true
        $body = $m.Value
        $body.Contains("'.env'") | Should Be $true
        $body.Contains("'" + $InstallCompleteMarker + "'") | Should Be $true
        $body.Contains('SYSTEM\CurrentControlSet\Services\F7FIVE0-API') | Should Be $true
    }
}
