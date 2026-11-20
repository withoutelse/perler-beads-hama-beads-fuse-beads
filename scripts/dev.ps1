$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
}

$python = Join-Path $root ".venv\Scripts\python.exe"
& $python -m pip install -e "apps/api[dev]"
Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "app.main:app", "--app-dir", "apps/api", "--reload"
) -WorkingDirectory $root -WindowStyle Hidden

Write-Host "API: http://127.0.0.1:8000"
Write-Host "Frontend: cd apps/web; pnpm install; pnpm run dev"
