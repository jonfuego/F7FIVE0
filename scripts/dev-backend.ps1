# Run both backend services locally for development.
# Opens two new PowerShell windows so both uvicorn processes are visible.
# From repo root:  .\scripts\dev-backend.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend  = Join-Path $RepoRoot "backend"
$Venv     = Join-Path $Backend ".venv\Scripts\Activate.ps1"

if (-not (Test-Path $Venv)) {
    throw "Python venv missing at $Venv. From backend\: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt"
}

$ApiCmd    = "cd `"$Backend`"; . `"$Venv`"; `$env:PYTHONPATH = `"$Backend`"; uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload"
$StreamCmd = "cd `"$Backend`"; . `"$Venv`"; `$env:PYTHONPATH = `"$Backend`"; uvicorn app.stream:app --host 127.0.0.1 --port 8002 --reload"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $ApiCmd
Start-Process powershell -ArgumentList "-NoExit", "-Command", $StreamCmd

Write-Host "API:    http://127.0.0.1:8001/api/health"
Write-Host "Stream: http://127.0.0.1:8002/stream/health"
