# Pester tests for the fast first install (common.ps1): Get-PgPlan (what Setup
# does about PostgreSQL), Test-VcRuntimeNeeded, Expand-Zip and Find-PgBinDir.
#
# The EnterpriseDB installer took 15 to 30 minutes of a 30-minute first install
# and failed winget's validation. F7FIVE0 now unpacks its own PostgreSQL into
# runtime\pgsql and runs it as F7FIVE0-Postgres on data\pgdata; an upgrade of
# an install that uses a system PostgreSQL keeps it.
#
# Works in Pester 3 and Pester 5 (Describe / It / Should Be only); every It loads
# its own copy of the common.ps1 functions. No admin rights, no services.
# Run: Invoke-Pester installer\tests\fast-install.Tests.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

Describe "Get-PgPlan" {
    It "a new install gets F7FIVE0's own PostgreSQL: unpack, initdb, register" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $p = Get-PgPlan $false $false $false "" "16.16-2" $false
        $p.Mode | Should Be "private"
        $p.Extract | Should Be $true
        $p.Init | Should Be $true
        $p.Register | Should Be $true
    }
    It "an upgrade of an install that uses a system PostgreSQL keeps it and does nothing" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $p = Get-PgPlan $true $false $false "" "16.16-2" $false
        $p.Mode | Should Be "legacy"
        $p.Extract | Should Be $false
        $p.Init | Should Be $false
        $p.Register | Should Be $false
    }
    It "an upgrade of an install with its own PostgreSQL at the same version changes nothing" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $p = Get-PgPlan $true $true $true "16.16-2" "16.16-2" $true
        $p.Mode | Should Be "private"
        $p.Extract | Should Be $false
        $p.Init | Should Be $false
        $p.Register | Should Be $false
    }
    It "a new pinned PostgreSQL build replaces the binaries, never the cluster" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $p = Get-PgPlan $true $true $true "16.16-2" "16.17-1" $true
        $p.Extract | Should Be $true
        $p.Init | Should Be $false
    }
    It "a reinstall after an uninstall that kept data\ puts binaries and service back, no initdb" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $p = Get-PgPlan $true $true $false "" "16.16-2" $false
        $p.Mode | Should Be "private"
        $p.Extract | Should Be $true
        $p.Init | Should Be $false
        $p.Register | Should Be $true
    }
    It "a rerun after a first install that stopped after initdb reuses the cluster" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $p = Get-PgPlan $false $true $true "16.16-2" "16.16-2" $false
        $p.Init | Should Be $false
        $p.Register | Should Be $true
    }
}

Describe "Test-VcRuntimeNeeded" {
    It "is needed when the runtime is not installed" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        (Test-VcRuntimeNeeded "" "" "14.40") | Should Be $true
        (Test-VcRuntimeNeeded "0" "v14.51.36247.00" "14.40") | Should Be $true
    }
    It "is needed when the installed runtime is older than the minimum" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        (Test-VcRuntimeNeeded "1" "v14.29.30133.00" "14.40") | Should Be $true
    }
    It "is not needed when the installed runtime is new enough" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        (Test-VcRuntimeNeeded "1" "v14.51.36247.00" "14.40") | Should Be $false
        (Test-VcRuntimeNeeded "1" "14.40.0.0" "14.40") | Should Be $false
    }
    It "treats an unreadable version as needed" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        (Test-VcRuntimeNeeded "1" "garbage" "14.40") | Should Be $true
    }
}

Describe "Expand-Zip" {
    It "unpacks a whole zip, and only the folders asked for" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = Join-Path ([IO.Path]::GetTempPath()) ("f7-expand-zip-" + [guid]::NewGuid().ToString("N"))
        try {
            $src = Join-Path $root "src"
            New-Item -ItemType Directory -Force -Path (Join-Path $src "pgsql\bin"), (Join-Path $src "pgsql\pgAdmin") | Out-Null
            Set-Content -Path (Join-Path $src "pgsql\bin\postgres.exe") -Value "x" -Encoding ASCII
            Set-Content -Path (Join-Path $src "pgsql\pgAdmin\big.txt") -Value "y" -Encoding ASCII
            $zip = Join-Path $root "pg.zip"
            Compress-Archive -Path (Join-Path $src "pgsql") -DestinationPath $zip
            $all = Join-Path $root "all"
            Expand-Zip $zip $all
            (Test-Path (Join-Path $all "pgsql\bin\postgres.exe")) | Should Be $true
            (Test-Path (Join-Path $all "pgsql\pgAdmin\big.txt")) | Should Be $true
            $some = Join-Path $root "some"
            Expand-Zip $zip $some @("pgsql/bin")
            (Test-Path (Join-Path $some "pgsql\bin\postgres.exe")) | Should Be $true
            (Test-Path (Join-Path $some "pgsql\pgAdmin")) | Should Be $false
        } finally { Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
    }
}

Describe "Find-PgBinDir" {
    It "prefers F7FIVE0's own runtime\pgsql\bin" {
        . (Join-Path $PSScriptRoot "..\common.ps1")
        $root = Join-Path ([IO.Path]::GetTempPath()) ("f7-pgbin-" + [guid]::NewGuid().ToString("N"))
        try {
            $bin = Join-Path $root "runtime\pgsql\bin"
            New-Item -ItemType Directory -Force -Path $bin | Out-Null
            Set-Content -Path (Join-Path $bin "pg_dump.exe") -Value "x" -Encoding ASCII
            (Find-PgBinDir $root) | Should Be $bin
        } finally { Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
    }
}
