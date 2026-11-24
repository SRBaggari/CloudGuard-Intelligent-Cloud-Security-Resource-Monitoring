# Start CloudGuard locally on Windows (backend + frontend in two windows).
# Run from the repository root:  powershell -ExecutionPolicy Bypass -File deployment\scripts\start-windows.ps1
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

if (-not (Test-Path "$root\backend\.venv")) {
    Write-Host "Creating Python virtual environment..."
    Push-Location "$root\backend"
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements-dev.txt
    Pop-Location
}
if (-not (Test-Path "$root\backend\.env")) {
    Write-Warning "backend\.env not found - copy .env.example to backend\.env and set DATABASE_URL / JWT_SECRET_KEY."
}
if (-not (Test-Path "$root\frontend\node_modules")) {
    Push-Location "$root\frontend"; npm install; Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Host "CloudGuard starting: http://localhost:5173  (API docs: http://127.0.0.1:8000/docs)"
