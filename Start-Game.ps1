$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'The .venv virtual environment was not found.'
}

Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    Write-Host 'Building the game interface...' -ForegroundColor Cyan
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'The Angular build failed.' }
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'The game is ready at http://localhost:8000' -ForegroundColor Green
Write-Host 'Press Ctrl+C to stop it.' -ForegroundColor DarkGray
& $PythonPath -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir $ProjectRoot
