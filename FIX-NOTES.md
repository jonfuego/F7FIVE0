# fix/install-native-stderr

## What was wrong
install.ps1 runs with `$ErrorActionPreference = "Stop"` and called the venv Python
(pip, compileall, alembic, `app.cli create-admin`) directly. alembic logs its INFO
lines to stderr. When install.ps1's output is redirected (for example
`install.ps1 -ConfigFile x.json *> log.txt`, the way a hand or scripted run might
save it), Windows PowerShell 5.1 turns each stderr line into an error record, and
"Stop" ends the install at "[12] Database migrations" with
`TerminatingError(python.exe): ... INFO [alembic.runtime.migration] Context impl PostgresqlImpl.`

Found while running hand test I-14 on the FuegoTest VM (the test harness saved
the output with `*>`). Setup and Admin > Updates run install.ps1 without
redirection, so normal installs were not affected; a by-hand run that saves its
output was.

## Fix
New `Invoke-VenvPy` helper in install.ps1 runs the venv Python with "Continue"
(restoring the old preference after) and the callers keep judging the result by
`$LASTEXITCODE`, same pattern the script already uses for psql and sc.exe. The
four `& $VenvPy` calls use it.

## Files
- installer/install.ps1
- installer/tests/native-stderr.Tests.ps1 (new, 4 tests)

## Tests
- `Invoke-Pester installer/tests` (Pester 3.4, PowerShell 5.1): 78 passed, 0 failed
  (74 existing + 4 new: no stop on redirected stderr, exit code kept, the bare
  call does stop (the bug), and no bare `& $VenvPy` left in install.ps1).
- ParseFile on install.ps1: 0 errors. ASCII only.

## For Jon
Not run through a real install. Merges cleanly beside fix/rerun-after-failed-install
(different lines of install.ps1).
