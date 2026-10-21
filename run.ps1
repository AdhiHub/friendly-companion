# Start Gethu (Windows). Runs setup automatically if needed.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# --- make sure the app is set up -----------------------------------------------
if (-not (Test-Path .venv)) {
    Write-Host "First run - setting up Gethu..."
    Write-Host ""
    & .\setup.ps1
}

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    Write-Host "x The Python environment looks broken." -ForegroundColor Red
    Write-Host "  Fix it by running:  Remove-Item -Recurse -Force .venv ; .\setup.ps1"
    exit 1
}

if (-not (Test-Path .env)) {
    Write-Host "! No .env yet - creating one from the example." -ForegroundColor Yellow
    Copy-Item .env.example .env
}

$keyLine = Select-String -Path .env -Pattern '^GEMINI_API_KEY=.+' -ErrorAction SilentlyContinue
if (-not $keyLine) {
    Write-Host "! No Gemini API key is set, so Gethu can't reply yet." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. Get a free key:  https://aistudio.google.com/apikey"
    Write-Host "  2. Put it in .env:  GEMINI_API_KEY=your_key_here"
    Write-Host ""
    Write-Host "  Starting anyway - the UI will open, but replies will fail."
    Write-Host ""
}

$host_ = if ($env:GETHU_HOST) { $env:GETHU_HOST } else { '127.0.0.1' }
$port  = if ($env:GETHU_PORT) { $env:GETHU_PORT } else { '8000' }

# --- warn early if the port is taken --------------------------------------------
$portBusy = $false
try {
    $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) { $portBusy = $true }
} catch { }

if ($portBusy) {
    Write-Host "x Port $port is already in use." -ForegroundColor Red
    Write-Host "  Start on a different one:  `$env:GETHU_PORT='8001'; .\run.ps1"
    exit 1
}

Write-Host ""
Write-Host "  Gethu is starting..." -ForegroundColor Green
Write-Host "  Open:  http://${host_}:${port}"
Write-Host "  Stop:  Ctrl + C"
Write-Host ""
Write-Host "  If the browser shows an old version, press Ctrl + Shift + R." -ForegroundColor DarkGray
Write-Host ""

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host $host_ --port $port
