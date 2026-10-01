<#
.SYNOPSIS
  Registers the "F7FIVE0-Backup" Windows scheduled task: runs
  scripts\backup-f7five0.ps1 nightly at 03:30 as the account you choose.

.DESCRIPTION
  The task must run whether or not anyone is logged in, and BACKUP_DEST is
  often a network share, so it registers with LogonType=Password using
  stored credentials for -RunAs. An S4U / "run whether logged on or
  not without password" logon can't authenticate to a network share, which
  is exactly where the backup writes, so stored creds are required.

  Run this once from an elevated PowerShell. It prompts for the -RunAs
  password (never takes it on the command line) and, after registering,
  exports the task definition to scripts\F7FIVE0-Backup.task.xml so the
  registration is auditable from the repo.

  Re-running replaces the existing task.
#>
[CmdletBinding()]
param(
    [string] $TaskName = 'F7FIVE0-Backup',
    [string] $RunAs    = "$env:USERDOMAIN\$env:USERNAME",
    [string] $At       = '03:30'
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Script   = Join-Path $RepoRoot 'scripts\backup-f7five0.ps1'
if (-not (Test-Path $Script)) { throw "backup script not found: $Script" }

$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwsh) { $pwsh = (Get-Command powershell).Source }

$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"$Script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Write-Host "Registering '$TaskName' to run $Script daily at $At as $RunAs."
Write-Host "Enter the password for $RunAs (needed so the task can reach the NAS while you're logged out):"
$cred = Get-Credential -UserName $RunAs -Message "Password for $RunAs (F7FIVE0-Backup task)"

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Highest `
    -User $cred.UserName -Password $cred.GetNetworkCredential().Password `
    -Description 'Nightly F7FIVE0 pg_dump + art/metadata-cache mirror to BACKUP_DEST.' `
    -Force | Out-Null

# Export the registered definition next to the scripts for auditability.
$xmlPath = Join-Path $RepoRoot 'scripts\F7FIVE0-Backup.task.xml'
Export-ScheduledTask -TaskName $TaskName | Set-Content -Path $xmlPath -Encoding UTF8
Write-Host "Registered. Definition exported to $xmlPath"

schtasks /query /tn $TaskName /fo LIST | Select-String 'TaskName|Next Run Time|Schedule|Run As User'
