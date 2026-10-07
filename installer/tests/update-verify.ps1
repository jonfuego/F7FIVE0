# update-verify.ps1
# Exercises installer\update.ps1 (the SYSTEM updater task) OFFLINE, with no
# real install, no PostgreSQL, and no network. Setup and pg_dump / pg_restore
# are one small stub exe (compiled below) that logs what it was asked to do.
# Health checks hit fake API / stream / web endpoints on loopback ports.
#
# Covers:
#   - a SHA-256 mismatch refuses, before anything is backed up or installed
#   - a downgrade (and the same version) refuses
#   - a Setup path outside <data>\updates\incoming refuses
#   - a "signed" request for an unsigned file refuses (Authenticode re-check)
#   - a missing cached Setup for the installed version refuses (no way back)
#   - the happy path: verify, pg_dump, Setup with the silent flags, health
#     checks, status.json phases ending in "done"
#   - a failed health check restores the dump (pg_restore --clean) and runs the
#     cached previous Setup, ending in "rolled_back"
#   - a Setup that exits non-zero, and one that never changes the version
#   - semver compare (Compare-SemVer in common.ps1), including prereleases
#   - a silent upgrade keeps .env values, contact email, ports, TMDB key
#   - the installer wiring: version.json, Setup cache, F7FIVE0-Update task
#
# Exits NON-ZERO on any failure, zero when everything passes.
# Run: powershell -File installer\tests\update-verify.ps1
# Windows PowerShell 5.1 compatible, ASCII only.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$installerDir = (Resolve-Path (Join-Path $here "..")).Path
. (Join-Path $installerDir "common.ps1")
$updater = Join-Path $installerDir "update.ps1"

$fails = 0
function Check([string]$name, [bool]$cond) {
    if ($cond) { Write-Host "PASS: $name" }
    else { Write-Host "FAIL: $name"; $script:fails++ }
}

$work = Join-Path $env:TEMP ("f7five0-updverify-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
$serverPs = $null
$serverHandle = $null

function Get-FreePort {
    $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    $l.Start()
    $p = ([System.Net.IPEndPoint]$l.LocalEndpoint).Port
    $l.Stop()
    return $p
}

try {
    # -----------------------------------------------------------------------
    # The stub: Setup, pg_dump, and pg_restore in one exe. It acts by its own
    # file name and reports to F7_STUB_LOG.
    # -----------------------------------------------------------------------
    $src = @'
using System;
using System.IO;
using System.Reflection;

public static class Stub {
    public static int Main(string[] args) {
        string exe = Assembly.GetEntryAssembly().Location;
        string self = Path.GetFileNameWithoutExtension(exe);
        string log = Environment.GetEnvironmentVariable("F7_STUB_LOG");
        string root = Environment.GetEnvironmentVariable("F7_STUB_ROOT");
        string line = self + " " + string.Join(" ", args);
        if (Environment.GetEnvironmentVariable("PGPASSWORD") != null) line += " [PGPASSWORD set]";
        if (!string.IsNullOrEmpty(log)) File.AppendAllText(log, line + "\r\n");
        string prefix = "F7FIVE0-Setup-";
        if (self.StartsWith(prefix)) {
            string ver = self.Substring(prefix.Length);
            if (Environment.GetEnvironmentVariable("F7_STUB_SETUP_FAIL") == ver) return 5;
            string cache = Path.Combine(root, "data", "updates", "setup");
            Directory.CreateDirectory(cache);
            string cached = Path.Combine(cache, self + ".exe");
            // Like Setup's [Files] entry: no copy when running from the cache itself.
            if (!string.Equals(exe, cached, StringComparison.OrdinalIgnoreCase)) File.Copy(exe, cached, true);
            if (Environment.GetEnvironmentVariable("F7_STUB_SETUP_NOWRITE") != ver)
                File.WriteAllText(Path.Combine(root, "version.json"), "{\"version\": \"" + ver + "\"}");
            return 0;
        }
        if (self == "pg_dump") {
            for (int i = 0; i < args.Length; i++) {
                if (args[i] == "-f" && i + 1 < args.Length) File.WriteAllText(args[i + 1], "DUMP");
                if (args[i].StartsWith("--file=")) File.WriteAllText(args[i].Substring(7), "DUMP");
            }
            return Environment.GetEnvironmentVariable("F7_STUB_DUMP_FAIL") == "1" ? 4 : 0;
        }
        if (self == "pg_restore") {
            return Environment.GetEnvironmentVariable("F7_STUB_RESTORE_FAIL") == "1" ? 3 : 0;
        }
        return 0;
    }
}
'@
    $stubExe = Join-Path $work "stub.exe"
    Add-Type -TypeDefinition $src -OutputAssembly $stubExe -OutputType ConsoleApplication
    Check "stub exe compiled" (Test-Path $stubExe)

    $pgBin = Join-Path $work "pgbin"
    New-Item -ItemType Directory -Path $pgBin | Out-Null
    Copy-Item $stubExe (Join-Path $pgBin "pg_dump.exe")
    Copy-Item $stubExe (Join-Path $pgBin "pg_restore.exe")

    # -----------------------------------------------------------------------
    # Fake API / stream / web. Reads <current root>\version.json on each
    # request; /stream/health answers 503 while that version is listed in
    # <root>\broken-version.txt.
    # -----------------------------------------------------------------------
    $apiPort = Get-FreePort; $streamPort = Get-FreePort; $webPort = Get-FreePort
    $rootFile = Join-Path $work "current-root.txt"
    $stopFile = Join-Path $work "server.stop"
    $serverScript = {
        param($ports, $rootFile, $stopFile)
        $listeners = @()
        foreach ($p in $ports) {
            $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
            $l.Start()
            $listeners += $l
        }
        while (-not (Test-Path $stopFile)) {
            $any = $false
            foreach ($l in $listeners) {
                if (-not $l.Pending()) { continue }
                $any = $true
                $c = $l.AcceptTcpClient()
                try {
                    $c.ReceiveTimeout = 2000
                    $s = $c.GetStream()
                    $buf = New-Object byte[] 4096
                    $n = $s.Read($buf, 0, 4096)
                    $req = [Text.Encoding]::ASCII.GetString($buf, 0, $n)
                    $path = ($req -split ' ')[1]
                    $port = ([System.Net.IPEndPoint]$l.LocalEndpoint).Port
                    $root = ""
                    try { $root = ([IO.File]::ReadAllText($rootFile)).Trim() } catch { }
                    $ver = "unknown"
                    try {
                        $j = [IO.File]::ReadAllText((Join-Path $root "version.json"))
                        if ($j -match '"version"\s*:\s*"([^"]+)"') { $ver = $matches[1] }
                    } catch { }
                    $broken = $false
                    try {
                        $bv = ([IO.File]::ReadAllText((Join-Path $root "broken-version.txt"))).Trim()
                        if ($bv -eq $ver) { $broken = $true }
                    } catch { }
                    $code = 404; $body = "not found"
                    if ($port -eq $ports[0] -and $path -eq "/api/health") { $code = 200; $body = '{"status":"ok","version":"' + $ver + '"}' }
                    elseif ($port -eq $ports[1] -and $path -eq "/stream/health") { if ($broken) { $code = 503; $body = "down" } else { $code = 200; $body = '{"status":"ok"}' } }
                    elseif ($port -eq $ports[2] -and $path -eq "/login") { $code = 200; $body = "login" }
                    $text = if ($code -eq 200) { "OK" } elseif ($code -eq 503) { "Service Unavailable" } else { "Not Found" }
                    $bytes = [Text.Encoding]::UTF8.GetBytes($body)
                    $head = "HTTP/1.1 $code $text`r`nContent-Type: application/json`r`nContent-Length: $($bytes.Length)`r`nConnection: close`r`n`r`n"
                    $hb = [Text.Encoding]::ASCII.GetBytes($head)
                    $s.Write($hb, 0, $hb.Length)
                    $s.Write($bytes, 0, $bytes.Length)
                    $s.Flush()
                } catch { } finally { $c.Close() }
            }
            if (-not $any) { Start-Sleep -Milliseconds 20 }
        }
        foreach ($l in $listeners) { $l.Stop() }
    }
    $serverPs = [PowerShell]::Create()
    [void]$serverPs.AddScript($serverScript).AddArgument(@($apiPort, $streamPort, $webPort)).AddArgument($rootFile).AddArgument($stopFile)
    $serverHandle = $serverPs.BeginInvoke()
    Start-Sleep -Milliseconds 500

    # -----------------------------------------------------------------------
    # Fixture builders
    # -----------------------------------------------------------------------
    function New-Fixture([string]$name, [string]$installed = "1.0.0", [bool]$cachePrevious = $true) {
        $install = Join-Path $work "$name\install"
        $data = Join-Path $install "data"
        foreach ($d in @("data\updates\incoming", "data\updates\setup", "data\updates\backup", "data\updates\run", "logs")) {
            New-Item -ItemType Directory -Force -Path (Join-Path $install $d) | Out-Null
        }
        Set-Content -Path (Join-Path $install ".env") -Encoding ASCII -Value @(
            "DATABASE_URL=postgresql+psycopg://f7five0:s3cretpw@127.0.0.1:5432/f7five0",
            "API_PORT=$apiPort", "STREAM_PORT=$streamPort", "WEB_PORT=$webPort"
        )
        Set-Content -Path (Join-Path $install "version.json") -Encoding ASCII -Value ('{"version": "' + $installed + '"}')
        if ($cachePrevious) {
            Copy-Item $stubExe (Join-Path $data "updates\setup\F7FIVE0-Setup-$installed.exe")
        }
        Set-Content -Path $rootFile -Value $install -Encoding ASCII
        $log = Join-Path $work "$name.stub.log"
        if (Test-Path $log) { Remove-Item $log }
        $env:F7_STUB_LOG = $log
        $env:F7_STUB_ROOT = $install
        foreach ($v in "F7_STUB_SETUP_FAIL", "F7_STUB_SETUP_NOWRITE", "F7_STUB_DUMP_FAIL", "F7_STUB_RESTORE_FAIL") {
            Remove-Item "env:$v" -ErrorAction SilentlyContinue
        }
        return @{ Install = $install; Data = $data; Log = $log; Name = $name }
    }

    # A staged Setup (the stub under the real file name) and its request.
    function New-Request($fx, [string]$version, [string]$source = "github", [string]$folder = "incoming", [string]$sha = "") {
        $dir = Join-Path $fx.Data "updates\$folder"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $path = Join-Path $dir "F7FIVE0-Setup-$version.exe"
        Copy-Item $stubExe $path -Force
        if (-not $sha) { $sha = (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLowerInvariant() }
        $id = [Guid]::NewGuid().ToString("N")
        $req = [ordered]@{ id = $id; setup_path = $path; sha256 = $sha; version = $version; source = $source }
        $json = $req | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $fx.Data "updates\request.json"), $json, (New-Object Text.UTF8Encoding($false)))
        return @{ Id = $id; Path = $path; Sha = $sha; Version = $version }
    }

    function Invoke-Updater($fx, [int]$healthSeconds = 10) {
        $out = Join-Path $work ($fx.Name + ".updater.out.txt")
        $err = Join-Path $work ($fx.Name + ".updater.err.txt")
        $p = Start-Process -FilePath "powershell.exe" -PassThru -Wait -NoNewWindow `
            -RedirectStandardOutput $out -RedirectStandardError $err `
            -ArgumentList @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$updater`"",
                "-InstallDir", "`"$($fx.Install)`"", "-FromRequest", "-PgBin", "`"$pgBin`"", "-HealthTimeoutSeconds", "$healthSeconds")
        return $p.ExitCode
    }

    # Printed when a scenario's checks fail, so the cause is in the output.
    function Show-Debug($fx) {
        $st = Get-Status $fx
        Write-Host ("  [debug] status: " + $(if ($st) { ($st | ConvertTo-Json -Compress -Depth 4) } else { "(none)" }))
        foreach ($suffix in @("updater.out.txt", "updater.err.txt")) {
            $p = Join-Path $work ($fx.Name + "." + $suffix)
            if (Test-Path $p) { Get-Content $p -Tail 12 | ForEach-Object { Write-Host "  [debug] $suffix : $_" } }
        }
        $lg = Get-ChildItem (Join-Path $fx.Install "logs") -Filter "update-*.log" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($lg) { Get-Content $lg.FullName -Tail 15 | ForEach-Object { Write-Host "  [debug] log : $_" } }
    }
    function Get-Status($fx) {
        $f = Join-Path $fx.Data "updates\status.json"
        if (-not (Test-Path $f)) { return $null }
        return (Get-Content -Raw -Path $f | ConvertFrom-Json)
    }
    function Get-StubLines($fx) {
        if (-not (Test-Path $fx.Log)) { return @() }
        return @(Get-Content -Path $fx.Log)
    }
    function Index-Of([string[]]$lines, [string]$pattern, [int]$after = -1) {
        for ($i = $after + 1; $i -lt $lines.Count; $i++) { if ($lines[$i] -match $pattern) { return $i } }
        return -1
    }
    function Installed-Version($fx) {
        $j = Get-Content -Raw -Path (Join-Path $fx.Install "version.json") | ConvertFrom-Json
        return $j.version
    }

    # -----------------------------------------------------------------------
    # 1. Hash mismatch refuses, before any backup or install
    # -----------------------------------------------------------------------
    $fx = New-Fixture "hash-mismatch"
    $r = New-Request $fx "1.1.0" "github" "incoming" ("0" * 64)
    $code = Invoke-Updater $fx
    $st = Get-Status $fx
    $lines = Get-StubLines $fx
    Check "hash mismatch: updater exits non-zero" ($code -ne 0)
    Check "hash mismatch: status is failed" ($st -and $st.phase -eq "failed")
    Check "hash mismatch: error names the checksum" ($st -and ("$($st.error)" -match "(?i)sha-?256|checksum|hash"))
    Check "hash mismatch: no pg_dump ran" ((Index-Of $lines "^pg_dump") -lt 0)
    Check "hash mismatch: Setup never ran" ((Index-Of $lines "^F7FIVE0-Setup-") -lt 0)
    Check "hash mismatch: installed version unchanged" ((Installed-Version $fx) -eq "1.0.0")
    Check "hash mismatch: request.json consumed" (-not (Test-Path (Join-Path $fx.Data "updates\request.json")))

    # -----------------------------------------------------------------------
    # 2. Downgrade and same-version refuse
    # -----------------------------------------------------------------------
    foreach ($v in @("0.9.0", "1.0.0")) {
        $fx = New-Fixture "downgrade-$v"
        $r = New-Request $fx $v
        $code = Invoke-Updater $fx
        $st = Get-Status $fx
        $lines = Get-StubLines $fx
        Check "version $v (installed 1.0.0): updater exits non-zero" ($code -ne 0)
        Check "version ${v}: status is failed and says not newer" ($st -and $st.phase -eq "failed" -and ("$($st.error)" -match "(?i)newer|downgrade|same|lower"))
        Check "version ${v}: nothing was backed up or installed" (((Index-Of $lines "^pg_dump") -lt 0) -and ((Index-Of $lines "^F7FIVE0-Setup-") -lt 0))
    }
    # A prerelease of the installed number is lower than the release.
    $fx = New-Fixture "downgrade-pre" "0.1.0"
    $r = New-Request $fx "0.1.0-batch4"
    $code = Invoke-Updater $fx
    Check "prerelease 0.1.0-batch4 over installed 0.1.0 refuses" ($code -ne 0 -and (Get-Status $fx).phase -eq "failed")

    # -----------------------------------------------------------------------
    # 3. A path outside incoming refuses
    # -----------------------------------------------------------------------
    $fx = New-Fixture "outside-incoming"
    $r = New-Request $fx "1.1.0" "github" "elsewhere"
    $code = Invoke-Updater $fx
    $st = Get-Status $fx
    Check "path outside incoming: exits non-zero" ($code -ne 0)
    Check "path outside incoming: status failed, error names incoming" ($st -and $st.phase -eq "failed" -and ("$($st.error)" -match "(?i)incoming"))
    Check "path outside incoming: nothing ran" ((Index-Of (Get-StubLines $fx) "^(pg_dump|F7FIVE0-Setup-)") -lt 0)

    $fx = New-Fixture "traversal"
    $r = New-Request $fx "1.1.0" "github" "elsewhere"
    $sneaky = Join-Path $fx.Data "updates\incoming\..\elsewhere\F7FIVE0-Setup-1.1.0.exe"
    $req = [ordered]@{ id = $r.Id; setup_path = $sneaky; sha256 = $r.Sha; version = "1.1.0"; source = "github" }
    [IO.File]::WriteAllText((Join-Path $fx.Data "updates\request.json"), ($req | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    $code = Invoke-Updater $fx
    Check "incoming\..\ traversal refuses" ($code -ne 0 -and (Get-Status $fx).phase -eq "failed")
    Check "traversal: nothing ran" ((Index-Of (Get-StubLines $fx) "^(pg_dump|F7FIVE0-Setup-)") -lt 0)

    # -----------------------------------------------------------------------
    # 4. A signed request for an unsigned file refuses
    # -----------------------------------------------------------------------
    $fx = New-Fixture "unsigned-claims-signed"
    $r = New-Request $fx "1.1.0" "signed"
    $code = Invoke-Updater $fx
    $st = Get-Status $fx
    Check "signed source, unsigned file: exits non-zero" ($code -ne 0)
    Check "signed source, unsigned file: status failed, error names the signature" ($st -and $st.phase -eq "failed" -and ("$($st.error)" -match "(?i)signature|authenticode|signed"))
    Check "signed source, unsigned file: nothing ran" ((Index-Of (Get-StubLines $fx) "^(pg_dump|F7FIVE0-Setup-)") -lt 0)

    # -----------------------------------------------------------------------
    # 5. No cached Setup for the installed version: refuse (no way back)
    # -----------------------------------------------------------------------
    $fx = New-Fixture "no-rollback-copy" "1.0.0" $false
    $r = New-Request $fx "1.1.0"
    $code = Invoke-Updater $fx
    $st = Get-Status $fx
    Check "no cached previous Setup: refuses" ($code -ne 0 -and $st -and $st.phase -eq "failed" -and ("$($st.error)" -match "(?i)cached|roll"))
    Check "no cached previous Setup: nothing ran" ((Index-Of (Get-StubLines $fx) "^(pg_dump|F7FIVE0-Setup-)") -lt 0)

    # -----------------------------------------------------------------------
    # 6. Happy path
    # -----------------------------------------------------------------------
    $fx = New-Fixture "happy"
    $r = New-Request $fx "1.1.0"
    $code = Invoke-Updater $fx
    $st = Get-Status $fx
    $lines = Get-StubLines $fx
    $iDump = Index-Of $lines "^pg_dump"
    $iSetup = Index-Of $lines "^F7FIVE0-Setup-1\.1\.0 "
    Check "happy path: exits 0" ($code -eq 0)
    Check "happy path: status done" ($st -and $st.phase -eq "done")
    Check "happy path: installed version is now 1.1.0" ((Installed-Version $fx) -eq "1.1.0")
    Check "happy path: pg_dump ran before Setup" ($iDump -ge 0 -and $iSetup -gt $iDump)
    Check "happy path: pg_dump used the custom format and the F7FIVE0 database" ($iDump -ge 0 -and $lines[$iDump] -match "-Fc" -and $lines[$iDump] -match "-d f7five0" -and $lines[$iDump] -match "-U f7five0")
    Check "happy path: the DB password never went on a command line" (-not ($lines -match "s3cretpw"))
    Check "happy path: the DB password was passed by environment" ($iDump -ge 0 -and $lines[$iDump] -match "PGPASSWORD set")
    Check "happy path: Setup got /VERYSILENT" ($iSetup -ge 0 -and $lines[$iSetup] -match "/VERYSILENT")
    Check "happy path: Setup got /SUPPRESSMSGBOXES" ($iSetup -ge 0 -and $lines[$iSetup] -match "/SUPPRESSMSGBOXES")
    Check "happy path: Setup got /NORESTART" ($iSetup -ge 0 -and $lines[$iSetup] -match "/NORESTART")
    Check "happy path: Setup got /SP-" ($iSetup -ge 0 -and $lines[$iSetup] -match "/SP-")
    Check "happy path: Setup got a /LOG under logs" ($iSetup -ge 0 -and $lines[$iSetup] -match "update-$($r.Id)-setup\.log")
    $dumps = @(Get-ChildItem (Join-Path $fx.Data "updates\backup") -Filter "1.0.0-$($r.Id).dump" -ErrorAction SilentlyContinue)
    Check "happy path: dump file is named <from>-<id>.dump" ($dumps.Count -eq 1)
    $phases = @(); if ($st -and $st.phases) { $phases = @($st.phases) }
    $want = @("verifying", "backup", "installing", "health_check", "done")
    $inOrder = $true; $at = -1
    foreach ($ph in $want) { $k = [array]::IndexOf($phases, $ph); if ($k -le $at) { $inOrder = $false }; $at = $k }
    Check "happy path: status.json phases run verifying, backup, installing, health_check, done" $inOrder
    Check "happy path: status.json names the log" ($st -and "$($st.log)" -match "update-$($r.Id)\.log")
    Check "happy path: status.json has both versions" ($st -and $st.from_version -eq "1.0.0" -and $st.to_version -eq "1.1.0")
    Check "happy path: the previous Setup is still cached for the next rollback" (Test-Path (Join-Path $fx.Data "updates\setup\F7FIVE0-Setup-1.0.0.exe"))
    Check "happy path: the new Setup cached itself" (Test-Path (Join-Path $fx.Data "updates\setup\F7FIVE0-Setup-1.1.0.exe"))
    Check "happy path: the updater log exists" (Test-Path (Join-Path $fx.Install "logs\update-$($r.Id).log"))

    # -----------------------------------------------------------------------
    # 7. A failed health check restores the database and the previous Setup
    # -----------------------------------------------------------------------
    $fx = New-Fixture "rollback"
    Set-Content -Path (Join-Path $fx.Install "broken-version.txt") -Value "1.1.0" -Encoding ASCII
    $r = New-Request $fx "1.1.0"
    $code = Invoke-Updater $fx 8
    $st = Get-Status $fx
    $lines = Get-StubLines $fx
    $iDump = Index-Of $lines "^pg_dump"
    $iNew = Index-Of $lines "^F7FIVE0-Setup-1\.1\.0 "
    $iRestore = Index-Of $lines "^pg_restore"
    $iOld = Index-Of $lines "^F7FIVE0-Setup-1\.0\.0 "
    if ($code -ne 2) { Show-Debug $fx }
    Check "rollback: exits 2" ($code -eq 2)
    Check "rollback: status rolled_back" ($st -and $st.phase -eq "rolled_back")
    Check "rollback: error explains the new version did not come up" ($st -and "$($st.error)" -match "(?i)health|did not come up|stream")
    Check "rollback: order is pg_dump, new Setup, pg_restore, previous Setup" ($iDump -ge 0 -and $iNew -gt $iDump -and $iRestore -gt $iNew -and $iOld -gt $iRestore)
    Check "rollback: pg_restore used --clean and the dump from this run" ($iRestore -ge 0 -and $lines[$iRestore] -match "--clean" -and $lines[$iRestore] -match "1\.0\.0-$($r.Id)\.dump")
    Check "rollback: the previous Setup got the silent flags" ($iOld -ge 0 -and $lines[$iOld] -match "/VERYSILENT" -and $lines[$iOld] -match "/SUPPRESSMSGBOXES" -and $lines[$iOld] -match "/NORESTART")
    Check "rollback: installed version is back to 1.0.0" ((Installed-Version $fx) -eq "1.0.0")
    $phases = @(); if ($st -and $st.phases) { $phases = @($st.phases) }
    Check "rollback: phases include health_check then rolling_back then rolled_back" ([array]::IndexOf($phases, "health_check") -ge 0 -and [array]::IndexOf($phases, "rolling_back") -gt [array]::IndexOf($phases, "health_check") -and [array]::IndexOf($phases, "rolled_back") -gt [array]::IndexOf($phases, "rolling_back"))

    # -----------------------------------------------------------------------
    # 8. Setup exits non-zero: restore and previous Setup
    # -----------------------------------------------------------------------
    $fx = New-Fixture "setup-fails"
    $env:F7_STUB_SETUP_FAIL = "1.1.0"
    $r = New-Request $fx "1.1.0"
    $code = Invoke-Updater $fx 8
    $st = Get-Status $fx
    $lines = Get-StubLines $fx
    Check "failed Setup: rolled back" ($code -eq 2 -and $st -and $st.phase -eq "rolled_back")
    Check "failed Setup: restore and previous Setup ran" ((Index-Of $lines "^pg_restore") -ge 0 -and (Index-Of $lines "^F7FIVE0-Setup-1\.0\.0 ") -ge 0)
    Remove-Item env:F7_STUB_SETUP_FAIL -ErrorAction SilentlyContinue

    # -----------------------------------------------------------------------
    # 9. Setup "succeeds" but the version never changes: not a pass
    # -----------------------------------------------------------------------
    $fx = New-Fixture "version-never-changes"
    $env:F7_STUB_SETUP_NOWRITE = "1.1.0"
    $r = New-Request $fx "1.1.0"
    $code = Invoke-Updater $fx 8
    $st = Get-Status $fx
    Check "health check needs the new version: rolled back" ($code -eq 2 -and $st -and $st.phase -eq "rolled_back")
    Remove-Item env:F7_STUB_SETUP_NOWRITE -ErrorAction SilentlyContinue

    # -----------------------------------------------------------------------
    # 10. pg_dump fails: stop before touching the install
    # -----------------------------------------------------------------------
    $fx = New-Fixture "dump-fails"
    $env:F7_STUB_DUMP_FAIL = "1"
    $r = New-Request $fx "1.1.0"
    $code = Invoke-Updater $fx
    $st = Get-Status $fx
    Check "backup failure: failed, Setup never ran" ($code -ne 0 -and $st -and $st.phase -eq "failed" -and (Index-Of (Get-StubLines $fx) "^F7FIVE0-Setup-") -lt 0)
    Check "backup failure: installed version unchanged" ((Installed-Version $fx) -eq "1.0.0")
    Remove-Item env:F7_STUB_DUMP_FAIL -ErrorAction SilentlyContinue

    # -----------------------------------------------------------------------
    # 11. Compare-SemVer (common.ps1)
    # -----------------------------------------------------------------------
    $pairs = @(
        @("0.1.0-batch4", "0.1.0", -1), @("0.1.0", "0.1.0-batch4", 1), @("1.0.0", "1.0.0", 0),
        @("1.10.0", "1.9.0", 1), @("1.0.0-alpha", "1.0.0-alpha.1", -1), @("1.0.0-alpha.1", "1.0.0-beta", -1),
        @("1.0.0-beta.2", "1.0.0-beta.11", -1), @("1.0.0-rc.1", "1.0.0", -1), @("v1.2.0", "1.1.9", 1),
        @("0.0.0-dev", "0.0.1", -1)
    )
    foreach ($p in $pairs) {
        $got = Compare-SemVer $p[0] $p[1]
        Check ("Compare-SemVer {0} vs {1} is {2}" -f $p[0], $p[1], $p[2]) ($got -eq $p[2])
    }
    Check "Test-SemVer accepts 1.2.3 and 0.1.0-batch4" ((Test-SemVer "1.2.3") -and (Test-SemVer "0.1.0-batch4"))
    Check "Test-SemVer rejects junk" (-not ((Test-SemVer "1.2") -or (Test-SemVer "a.b.c") -or (Test-SemVer "") -or (Test-SemVer "1.2.3; calc")))

    # -----------------------------------------------------------------------
    # 12. Silent upgrade keeps settings (Merge-EnvFile is what install.ps1 uses)
    # -----------------------------------------------------------------------
    $envPath = Join-Path $work "upgrade.env"
    Set-Content -Path $envPath -Encoding ASCII -Value @(
        "# F7FIVE0 configuration.",
        "DATABASE_URL=postgresql+psycopg://f7five0:pw@127.0.0.1:5432/f7five0",
        "JWT_SECRET=keep-this-secret",
        "MUSICBRAINZ_USER_AGENT_EMAIL=jon@example.com",
        "TMDB_API_KEY=tmdbkey123",
        "LIBRARY_ROOT_MOVIES=\\fuegonas\The Hive\Movies",
        "PUBLIC_URL=https://media.example.com",
        "API_PORT=8101", "STREAM_PORT=8102", "WEB_PORT=3101",
        "CUSTOM_BY_HAND=yes"
    )
    # What a /VERYSILENT upgrade hands over: fresh secrets, blank answers.
    $want = [ordered]@{
        "ENVIRONMENT" = "production"
        "DATABASE_URL" = ""
        "JWT_SECRET" = "a-brand-new-random-secret"
        "MUSICBRAINZ_USER_AGENT_EMAIL" = ""
        "TMDB_API_KEY" = ""
        "LIBRARY_ROOT_MOVIES" = ""
        "API_PORT" = "8001"
        "STREAM_PORT" = "8002"
        "WEB_PORT" = "3001"
        "A_SETTING_ADDED_IN_THE_NEW_VERSION" = "fresh"
    }
    $added = Merge-EnvFile $envPath $want @{ "API_PORT" = "8101"; "STREAM_PORT" = "8102"; "WEB_PORT" = "3101" }
    $after = @{}
    foreach ($line in Get-Content $envPath) { if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { $after[$matches[1]] = $matches[2] } }
    Check "silent upgrade: contact email kept" ($after["MUSICBRAINZ_USER_AGENT_EMAIL"] -eq "jon@example.com")
    Check "silent upgrade: TMDB key kept" ($after["TMDB_API_KEY"] -eq "tmdbkey123")
    Check "silent upgrade: secrets kept (JWT_SECRET, DATABASE_URL)" ($after["JWT_SECRET"] -eq "keep-this-secret" -and $after["DATABASE_URL"] -like "postgresql+psycopg://f7five0:pw@*")
    Check "silent upgrade: library folder kept" ($after["LIBRARY_ROOT_MOVIES"] -eq "\\fuegonas\The Hive\Movies")
    Check "silent upgrade: public address kept" ($after["PUBLIC_URL"] -eq "https://media.example.com")
    Check "silent upgrade: ports kept" ($after["API_PORT"] -eq "8101" -and $after["STREAM_PORT"] -eq "8102" -and $after["WEB_PORT"] -eq "3101")
    Check "silent upgrade: hand-added keys kept" ($after["CUSTOM_BY_HAND"] -eq "yes")
    Check "silent upgrade: a new setting is added" ($after["A_SETTING_ADDED_IN_THE_NEW_VERSION"] -eq "fresh" -and $added -eq 2)
    $threw = $false
    $bare = Join-Path $work "bare.env"
    Set-Content -Path $bare -Encoding ASCII -Value @("WEB_PORT=3001")
    try { Merge-EnvFile $bare ([ordered]@{ "DATABASE_URL" = "" }) @{} | Out-Null } catch { $threw = $true }
    Check "an .env with no DATABASE_URL and none to add still stops Setup" $threw

    $iss = Get-Content -Raw -Path (Join-Path $installerDir "F7FIVE0.iss")
    $step = $iss.Substring($iss.IndexOf("procedure CurStepChanged"))
    $afterUpgradeBlock = $step.Substring($step.IndexOf("if not IsUpgrade then"))
    $afterUpgradeBlock = $afterUpgradeBlock.Substring($afterUpgradeBlock.IndexOf("end;"))
    $leak = @("tmdbKey", "webPort", "apiPort", "streamPort", "adminUser", "adminPassword", "moviesDir", "tvDir", "musicDir", "musicVideosDir", "openFirewall", "postgresPassword")
    $leaked = @($leak | Where-Object { $afterUpgradeBlock -match [regex]::Escape("JsonPair('$_'") })
    Check "iss: an upgrade sends only appVersion and contactEmail (answers are inside 'if not IsUpgrade')" ($leaked.Count -eq 0 -and $afterUpgradeBlock -match "JsonPair\('appVersion'" -and $afterUpgradeBlock -match "JsonPair\('contactEmail'")
    Check "iss: every answer page is skipped on upgrade" ($iss -match "(?s)function ShouldSkipPage.*?IsUpgrade and \(\(PageID = MediaPage\.ID\).*?PortsPage\.ID\)\)")

    # -----------------------------------------------------------------------
    # 13. Installer wiring
    # -----------------------------------------------------------------------
    $install = Get-Content -Raw -Path (Join-Path $installerDir "install.ps1")
    $uninstall = Get-Content -Raw -Path (Join-Path $installerDir "uninstall.ps1")
    $dist = Get-Content -Raw -Path (Join-Path $installerDir "build-dist.ps1")
    $upd = Get-Content -Raw -Path $updater
    Check "iss passes appVersion to install.ps1" ($iss -match "JsonPair\('appVersion', '\{#AppVersion\}'")
    Check "iss copies Setup itself into the updates Setup cache" ($iss -match '(?i)Source: "\{srcexe\}".*data\\updates\\setup.*F7FIVE0-Setup-\{#AppVersion\}\.exe')
    Check "iss skips that copy when Setup runs from the cache itself (a rollback)" ($iss -match 'Check: NotRunningFromSetupCache' -and $iss -match '(?s)function NotRunningFromSetupCache: Boolean;.*CompareText\(ExpandConstant\(''\{srcexe\}''\)')
    Check "install.ps1 reads appVersion and writes version.json" ($install -match 'Answer "appVersion"' -and $install -match 'version\.json' -and $install -match 'installed_at')
    Check "install.ps1 names the task F7FIVE0-Update" ($install -match '\$UpdateTask = "F7FIVE0-Update"')
    Check "install.ps1 registers it as SYSTEM" ($install -match '(?s)New-ScheduledTaskPrincipal -UserId "SYSTEM".{0,1200}Register-ScheduledTask -TaskName \$UpdateTask')
    Check "install.ps1's task runs the copy of update.ps1 under data\updates\run" ($install -match '\$UpdDir = Join-Path \$DataDir "updates"' -and $install -match '\$UpdRun = Join-Path \$UpdDir "run"' -and $install -match '\$updScript = Join-Path \$UpdRun "update\.ps1"' -and $install -match '-File `"\$updScript`"')
    Check "install.ps1 lets a -ServiceUser account read and start the update task" ($install -match 'GRGX' -and $install -match 'GetTask\(\$UpdateTask\)')
    Check "install.ps1 prunes the Setup cache to the current and previous copy" ($install -match 'Prune-SetupCache')
    Check "install.ps1 keeps the services' Windows account on upgrade" ($install -match 'KeepServiceAccount')
    Check "uninstall.ps1 removes the F7FIVE0-Update task" ($uninstall -match 'Unregister-ScheduledTask -TaskName "F7FIVE0-Update"')
    Check "build-dist.ps1 ships update.ps1" ($dist -match '"update\.ps1"')
    Check "update.ps1 runs Setup with the three silent flags" ($upd -match '/VERYSILENT' -and $upd -match '/SUPPRESSMSGBOXES' -and $upd -match '/NORESTART')
    Check "update.ps1 backs up with pg_dump -Fc and restores with pg_restore --clean" ($upd -match 'pg_dump' -and $upd -match '-Fc' -and $upd -match 'pg_restore' -and $upd -match '--clean')
    foreach ($f in @("update.ps1", "install.ps1", "common.ps1", "uninstall.ps1", "build-dist.ps1", "tests\update-verify.ps1")) {
        $bytes = [IO.File]::ReadAllBytes((Join-Path $installerDir $f))
        $bad = @($bytes | Where-Object { $_ -gt 127 }).Count
        Check "$f is ASCII only (Windows PowerShell 5.1 misreads UTF-8 without a BOM)" ($bad -eq 0)
    }
}
finally {
    try { New-Item -ItemType File -Path $stopFile -Force | Out-Null } catch { }
    if ($serverPs) {
        try { [void]$serverPs.EndInvoke($serverHandle) } catch { }
        $serverPs.Dispose()
    }
    foreach ($v in "F7_STUB_LOG", "F7_STUB_ROOT", "F7_STUB_SETUP_FAIL", "F7_STUB_SETUP_NOWRITE", "F7_STUB_DUMP_FAIL", "F7_STUB_RESTORE_FAIL") {
        Remove-Item "env:$v" -ErrorAction SilentlyContinue
    }
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
