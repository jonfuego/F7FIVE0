# Run the Next dev server.
# From repo root:  .\scripts\dev-frontend.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $RepoRoot "frontend"

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Push-Location $Frontend
    npm install
    Pop-Location
}

Push-Location $Frontend
try {
    npm run dev
} finally {
    Pop-Location
}
