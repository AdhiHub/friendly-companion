# Gethu one-command setup for Windows (PowerShell).
# Creates a virtual environment, installs dependencies and prepares .env.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Ok($m)   { Write-Host "v $m" -ForegroundColor Green }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "x $m" -ForegroundColor Red; exit 1 }

Write-Host "Gethu setup" -ForegroundColor White
Write-Host ""

# 1. Find Python ---------------------------------------------------------------
$py = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        try {
            $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])"
            $parts = $ver.Split('.')
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { $py = $candidate; break }
        } catch { }
    }
}
if (-not $py) {
    Die "Python 3.11+ not found. Install it from https://www.python.org/downloads/ and tick 'Add Python to PATH'."
}
Ok "Using $py ($(& $py --version 2>&1))"

# 2. Virtual environment -------------------------------------------------------
if (Test-Path .venv) {
    Ok "Reusing existing .venv"
} else {
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0) { Die "Could not create a virtual environment." }
    Ok "Created .venv"
}

# 3. Dependencies --------------------------------------------------------------
Write-Host "Installing dependencies (this can take a minute)..."
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "Dependency install failed." }
Ok "Dependencies installed"

# 4. .env ----------------------------------------------------------------------
if (Test-Path .env) {
    Ok ".env already exists - left untouched"
} else {
    Copy-Item .env.example .env
    Warn "Created .env - you must add your Gemini API key."
}

$keyLine = Select-String -Path .env -Pattern '^GEMINI_API_KEY=.+' -ErrorAction SilentlyContinue
if (-not $keyLine) {
    Write-Host ""
    Write-Host "One step left: add your free Gemini API key." -ForegroundColor White
    Write-Host "  1. Get a key:  https://aistudio.google.com/apikey"
    Write-Host "  2. Edit .env:  notepad .env"
    Write-Host "  3. Put it on the line:  GEMINI_API_KEY=your_key_here"
    Write-Host ""
    Write-Host "Then start Gethu with:  .\run.ps1"
} else {
    Write-Host ""
    Ok "API key detected. Start Gethu with: .\run.ps1"
}
