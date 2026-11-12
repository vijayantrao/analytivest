# One-command start for Analytivest on Windows (PowerShell).
# First run: creates the Python virtual environment, installs dependencies and builds the frontend.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location "$root\backend"
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    py -m venv .venv
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -r requirements.txt
}

if (-not (Test-Path "$root\frontend\dist\index.html")) {
    Write-Host "Building the frontend..."
    Push-Location "$root\frontend"
    npm install
    npm run build
    Pop-Location
}

Write-Host "Analytivest running at http://127.0.0.1:8000  (Ctrl+C to stop)"
Start-Process "http://127.0.0.1:8000"
.\.venv\Scripts\python run.py
