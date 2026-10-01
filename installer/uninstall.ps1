<#
.SYNOPSIS
  Removes the F7FIVE0 Windows services.

.DESCRIPTION
  Stops and removes F7FIVE0-API, F7FIVE0-Stream, and F7FIVE0-Web, and the
  "F7FIVE0 web" firewall rule. Your media is never touched.

  By default your settings, database, art cache, and watch history are
  KEPT, so reinstalling picks up where you left off. Pass -RemoveData to
  also drop the F7FIVE0 database and delete the data folder.

  A Cloudflare tunnel made by setup (F7FIVE0-Tunnel) is removed as a
  service; delete the tunnel itself in the Cloudflare dashboard if you like.
  Tailscale Funnel is switched off. The port-forwarding proxy (F7FIVE0-Proxy),
  its firewall rule, and the DuckDNS refresh task are removed; remove the
  port-forward rules on your router yourself.

  PostgreSQL, Python, and Tailscale are left installed
  because other software may use them. Remove them from Windows Settings >
  Apps if you no longer need them.
#>
[CmdletBinding()]
param(
    [string] $InstallDir = "C:\F7FIVE0",
    [switch] $RemoveData
)
#Requires -RunAsAdministrator
$ErrorActionPreference = "Continue"

$Nssm = Join-Path $InstallDir "bin\nssm.exe"
foreach ($svc in @("F7FIVE0-Proxy", "F7FIVE0-Tunnel", "F7FIVE0-Web", "F7FIVE0-Stream", "F7FIVE0-API")) {
    if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
        Write-Host "removing service $svc"
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        if (Test-Path $Nssm) { & $Nssm remove $svc confirm *> $null }
        else { & sc.exe delete $svc | Out-Null }
    }
}
Get-NetFirewallRule -DisplayName "F7FIVE0 web" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName "F7FIVE0 HTTPS" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Unregister-ScheduledTask -TaskName "F7FIVE0-DuckDNS" -Confirm:$false -ErrorAction SilentlyContinue

# Stop publishing through Tailscale Funnel (Tailscale itself stays installed).
$ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
if (Test-Path $ts) { & $ts funnel reset *> $null }

if ($RemoveData) {
    $envFile = Join-Path $InstallDir ".env"
    $saved = Join-Path $InstallDir "data\postgres-superuser.txt"
    $psql = Get-ChildItem "$env:ProgramFiles\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if ($psql -and (Test-Path $saved)) {
        $env:PGPASSWORD = (Get-Content $saved | Select-Object -Last 1).Trim()
        & $psql -h 127.0.0.1 -U postgres -d postgres -c "DROP DATABASE IF EXISTS f7five0;" | Out-Null
        & $psql -h 127.0.0.1 -U postgres -d postgres -c "DROP ROLE IF EXISTS f7five0;" | Out-Null
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
        Write-Host "dropped database f7five0"
    } elseif ($psql) {
        Write-Host "Database kept: run  DROP DATABASE f7five0; DROP ROLE f7five0;  in psql as 'postgres' to remove it."
    }
    foreach ($p in @((Join-Path $InstallDir "data"), $envFile)) {
        if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Host "deleted $p" }
    }
}
Write-Host "F7FIVE0 services removed."
