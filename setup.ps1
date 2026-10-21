# Gethu one-command setup for Windows (PowerShell).
# Checks everything first, then creates a virtual environment, installs 
# dependencies and prepares .env.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Ok($m)   { Write-Host "v $m" -ForegroundColor Green }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "x $m" -ForegroundColor Red }
function Die($m)  { Bad $m; exit 1 }

$problems = New-Object System.Collections.Generic.List[string]

Write-Host "Gethu setup" -ForegroundColor White
Write-Host ""

# ------------------------------------------------------------------ preflight
Write-Host "Checking your system" -ForegroundColor White

if (-not (Test-Path 'requirements.txt')) { Die "Run this from the Gethu folder (requirements.txt not found)." }
if (-not (Test-Path '.env.example'))     { Die "Run this from the Gethu folder (.env.example not found)." }

# 1. Python -----------------------------------------------------------------
$py = $null
$foundAny = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        try {
            $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver) {
                $foundAny = $candidate
                $parts = $ver.Split('.')
                if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { $py = $candidate; $pyVer = $ver; break }
            }
        } catch { }
    }
}

if ($py) {
    Ok "Python $pyVer"
} elseif ($foundAny) {
    Bad "Python $foundAny is too old - Gethu needs 3.11 or newer."
    Write-Host ""
    Write-Host "  Install Python 3.12+ from https://www.python.org/downloads/"
    Write-Host "  During install, tick 'Add Python to PATH', then run this script again."
    exit 1
} else {
    Bad "No Python found at all."
    Write-Host ""
    Write-Host "  Install Python 3.12+ from https://www.python.org/downloads/"
    Write-Host "  During install, tick 'Add Python to PATH', then run this script again."
    exit 1
}

# 2. venv module ------------------------------------------------------------
try {
    & $py -c "import venv" 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "Python venv module" }
    else { Bad "Python venv module is missing - reinstall Python from python.org."; exit 1 }
} catch {
    Bad "Python venv module is missing - reinstall Python from python.org."
    exit 1
}

# 3. Internet ---------------------------------------------------------------
try {
    $resp = Invoke-WebRequest -Uri 'https://pypi.org/simple/' -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
    Ok "Internet connection"
} catch {
    Warn "Could not reach pypi.org - pip may fail. Check your connection, firewall or proxy."
}

# 4. Disk space -------------------------------------------------------------
try {
    $drive = (Get-Item $PSScriptRoot).PSDrive
    $freeMb = [math]::Round((Get-PSDrive $drive.Name).Free / 1MB)
    if ($freeMb -ge 500) {
        Ok "$freeMb MB free disk space"
    } else {
        Bad "Only $freeMb MB free - Gethu needs about 500 MB."
        $problems.Add("Free up some disk space, then run this script again.")
    }
} catch { }

# 5. Port -------------------------------------------------------------------
$port = if ($env:GETHU_PORT) { $env:GETHU_PORT } else { '8000' }
$portBusy = $false
try {
    $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) { $portBusy = $true }
} catch { }

if ($portBusy) {
    Warn "Port $port is already in use - Gethu will fail to start on it."
    $problems.Add("Free port $port, or start Gethu on another one:`n     `$env:GETHU_PORT='8001'; .\run.ps1")
} else {
    Ok "Port $port is free"
}

Write-Host ""

if ($problems.Count -gt 0) {
    Write-Host "Fix these first:" -ForegroundColor Red
    foreach ($p in $problems) {
        Write-Host ""
        Write-Host "  - $p" -ForegroundColor Red
    }
    Write-Host ""
    exit 1
}

# ------------------------------------------------------------------- install
Write-Host "Setting up Gethu" -ForegroundColor White

if (Test-Path .venv) {
    Ok "Reusing existing .venv"
} else {
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Bad "Could not create a virtual environment."
        Write-Host "  Reinstall Python from https://www.python.org/downloads/ and retry."
        exit 1
    }
    Ok "Created .venv"
}

Write-Host "Installing dependencies (this can take a minute)..."
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Bad "Could not upgrade pip."
    Write-Host "  Check your internet connection (or proxy settings) and try again."
    exit 1
}
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Bad "Dependency install failed."
    Write-Host "  Check your internet connection, then run:  .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}
Ok "Dependencies installed"

if (Test-Path .env) {
    Ok ".env already exists - left untouched"
} else {
    Copy-Item .env.example .env
    Warn "Created .env - you still need to add your Gemini API key."
}

# --------------------------------------------------------------------- ready
Write-Host ""
$keyLine = Select-String -Path .env -Pattern '^GEMINI_API_KEY=.+' -ErrorAction SilentlyContinue

if (-not $keyLine) {
    Write-Host "Almost there - one step left: add your free Gemini API key." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. Get a key:  https://aistudio.google.com/apikey"
    Write-Host "  2. Open .env:  notepad .env"
    Write-Host "  3. Put it on the line:  GEMINI_API_KEY=your_key_here"
    Write-Host ""
    Write-Host "  Then start Gethu:  .\run.ps1"
} else {
    Ok "API key detected"
    Write-Host ""
    Write-Host "Gethu is ready." -ForegroundColor Green -NoNewline
    Write-Host "  Start it with:  .\run.ps1"
}
Write-Host ""
Write-Host "Suggested: a Chromium browser (Chrome, Edge, Brave) for voice input." -ForegroundColor DarkGray
Write-Host ""
