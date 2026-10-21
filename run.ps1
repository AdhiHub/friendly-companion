# Start Gethu (Windows). Runs setup automatically if needed.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

if (-not (Test-Path .venv)) {
    Write-Host "First run - setting up Gethu..."
    & .\setup.ps1
}

$host_ = if ($env:GETHU_HOST) { $env:GETHU_HOST } else { '127.0.0.1' }
$port  = if ($env:GETHU_PORT) { $env:GETHU_PORT } else { '8000' }

Write-Host ""
Write-Host "  Gethu is starting..."
Write-Host "  Open:  http://${host_}:${port}"
Write-Host "  Stop:  Ctrl + C"
Write-Host ""

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host $host_ --port $port
