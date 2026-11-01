# Pester tests for the private Node.js copy's folder rights in install.ps1.
# Move-Item keeps the ACL a folder had in %TEMP%, so after "Securing the install
# folder" the moved runtime\node must be reset to inherit the install folder's
# rights, or a -ServiceUser account can't run node.exe and F7FIVE0-Web fails to
# start (hand test I-14). The behavior test builds a folder with a private ACL
# under a test root, moves it like install.ps1 does, and checks the reset.
#
# Works in Pester 3 and Pester 5 (Describe / It / Should only). No admin rights.
# Run: Invoke-Pester installer\tests\node-acl.Tests.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

Describe "runtime\node folder rights" {
    It "install.ps1 resets runtime\node's ACL right after moving it in" {
        $text = Get-Content (Join-Path $PSScriptRoot "..\install.ps1") -Raw
        $move = $text.IndexOf('Move-Item (Get-ChildItem $unz | Select-Object -First 1).FullName $NodeDir')
        $move | Should Not Be -1
        $reset = $text.IndexOf('& icacls $NodeDir /reset /T /C /Q', $move)
        $reset | Should Not Be -1
        ($reset - $move) -lt 800 | Should Be $true
    }
    It "a moved folder keeps a private ACL until icacls /reset makes it inherit" {
        $root = Join-Path ([IO.Path]::GetTempPath()) ("f7acl-" + [guid]::NewGuid().ToString("N"))
        $src = Join-Path $root "src\node"; $dstParent = Join-Path $root "app\runtime"
        New-Item -ItemType Directory -Path $src, $dstParent -Force | Out-Null
        Set-Content (Join-Path $src "node.exe") "x"
        try {
            # Private source: no inheritance, only the current user.
            $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
            & icacls $src /inheritance:r /grant:r "*${me}:(OI)(CI)F" /T /C /Q | Out-Null
            $dst = Join-Path $dstParent "node"
            Move-Item $src $dst
            $inheritedBefore = @((Get-Acl (Join-Path $dst "node.exe")).Access | Where-Object { $_.IsInherited }).Count
            & icacls $dst /reset /T /C /Q | Out-Null
            $LASTEXITCODE | Should Be 0
            $inheritedAfter = @((Get-Acl (Join-Path $dst "node.exe")).Access | Where-Object { $_.IsInherited }).Count
            $inheritedBefore | Should Be 0
            ($inheritedAfter -gt 0) | Should Be $true
        } finally {
            & icacls $root /reset /T /C /Q | Out-Null
            Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
        }
    }
}
