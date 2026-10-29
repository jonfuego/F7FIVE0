# fix/node-acl-service-user

## What was wrong
Hand test I-14 (fresh install with `install.ps1 -ServiceUser .\f7svc`) on the
FuegoTest VM: the install stopped at "[18] Starting F7FIVE0" with
"Failed to start service 'F7FIVE0-Web'". API and Stream ran as .\f7svc; Web did not.
The nssm event said: `Program C:\F7FIVE0\runtime\node\node.exe couldn't be launched.
CreateProcess() failed: Access is denied.`

install.ps1 secures the install folder first ("Securing the install folder",
Set-InstallAcl resets runtime\ and the rest to inherit Users:RX). Node.js is
downloaded and unzipped later into %TEMP% and then `Move-Item`d to
runtime\node. A move on the same volume keeps the folder's ACL from %TEMP%
(the admin's profile: that admin, SYSTEM, Administrators only), so the service
account could not run node.exe. With the default LocalSystem services nobody
notices, because SYSTEM can. A later Setup over the top fixed it (its
Set-InstallAcl reset runtime\ with node already in place), which is why the
services ran as .\f7svc after the update in I-14. The same would hit an upgrade
that brings a new Node.js version on a -ServiceUser install.

ffmpeg and nssm are Copy-Item'd into bin\, so they inherit and are fine.

## Fix
Right after the move, `icacls runtime\node /reset /T /C /Q` so the folder
inherits the install folder's rights (Users RX, SYSTEM and Administrators full),
failing the install if icacls fails.

## Files
- installer/install.ps1
- installer/tests/node-acl.Tests.ps1 (new, 2 tests)

## Tests
- `Invoke-Pester installer/tests` (Pester 3.4, PowerShell 5.1): 76 passed, 0 failed.
- ParseFile on install.ps1: 0 errors; ASCII only.

## Evidence from the VM (1.0.18, before the fix)
- After the failed install: node.exe ACL = no Users entry (from %TEMP%); F7FIVE0-Web stopped.
- After Setup /VERYSILENT over it: node.exe `BUILTIN\Users:(I)(RX)`, all three services
  running as .\f7svc, web answers 307.

## For Jon
Re-run I-14 from the "Hermes base" snapshot with a Setup built from this branch:
the first install should end with all three services running as the account.
