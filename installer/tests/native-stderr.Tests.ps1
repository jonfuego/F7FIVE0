# Pester tests for install.ps1's Invoke-VenvPy: Python tools (pip, alembic,
# the app CLI) log INFO lines to stderr. When install.ps1's output is
# redirected (install.ps1 *> log), Windows PowerShell 5.1 turns those lines
# into error records, and with $ErrorActionPreference = "Stop" the first one
# ended the install at "Database migrations" (hand test I-14).
#
# Works in Pester 3 and Pester 5 (Describe / It / Should only). Every It loads
# its own copy of the function from install.ps1's AST, so nothing runs the
# installer. Needs no admin rights. cmd.exe stands in for python.exe.
# Run: Invoke-Pester installer\tests\native-stderr.Tests.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

function Get-InstallFunctionText([string]$name) {
    $path = Join-Path $PSScriptRoot "..\install.ps1"
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    $fn = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true) | Select-Object -First 1
    if (-not $fn) { throw "function $name not found in install.ps1" }
    return $fn.Extent.Text
}

Describe "Invoke-VenvPy" {
    It "does not stop on stderr output when the output is redirected" {
        . ([scriptblock]::Create((Get-InstallFunctionText "Invoke-VenvPy")))
        $VenvPy = "cmd.exe"
        $ErrorActionPreference = "Stop"
        $threw = $false
        try { $null = Invoke-VenvPy /c "echo INFO alembic 1>&2 & exit 0" *>&1 } catch { $threw = $true }
        $threw | Should Be $false
        $LASTEXITCODE | Should Be 0
        $ErrorActionPreference | Should Be "Stop"
    }
    It "keeps the tool's exit code so a real failure still fails" {
        . ([scriptblock]::Create((Get-InstallFunctionText "Invoke-VenvPy")))
        $VenvPy = "cmd.exe"
        $ErrorActionPreference = "Stop"
        $null = Invoke-VenvPy /c "echo boom 1>&2 & exit 3" *>&1
        $LASTEXITCODE | Should Be 3
    }
    It "a bare call with Stop and redirection does stop (the bug this guards)" {
        $ErrorActionPreference = "Stop"
        $threw = $false
        try { $null = & cmd.exe /c "echo INFO alembic 1>&2 & exit 0" 2>&1 } catch { $threw = $true }
        $threw | Should Be $true
    }
}

Describe "install.ps1 runs the venv Python through Invoke-VenvPy" {
    It "has no bare '& `$VenvPy' call outside the helper" {
        $path = Join-Path $PSScriptRoot "..\install.ps1"
        $helper = Get-InstallFunctionText "Invoke-VenvPy"
        $text = (Get-Content $path -Raw).Replace($helper, "")
        ($text -match '&\s*\$VenvPy\b') | Should Be $false
    }
}
