#!/usr/bin/env bash
# Gethu one-command setup for Linux / macOS.
# Checks everything first, then creates a virtual environment, installs
# dependencies and prepares .env.

set -euo pipefail

cd "$(dirname "$0")"

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s\n' "${GREEN}✓${RESET} $*"; }
warn() { printf '%s\n' "${YELLOW}!${RESET} $*"; }
bad()  { printf '%s\n' "${RED}✗${RESET} $*"; }
die()  { bad "$*"; exit 1; }

# Collected problems, printed together at the end.
PROBLEMS=()
note() { PROBLEMS+=("$*"); }

say "${BOLD}Gethu setup${RESET}"
say ""

# ------------------------------------------------------------------ preflight
say "${BOLD}Checking your system${RESET}"

# 1. Is this even a Gethu checkout? ------------------------------------------
[ -f requirements.txt ] || die "Run this from the Gethu folder (requirements.txt not found)."
[ -f .env.example ]     || die "Run this from the Gethu folder (.env.example not found)."

# 2. Python ---------------------------------------------------------------
PY=""
FOUND_ANY_PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    FOUND_ANY_PYTHON="$candidate"
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done

if [ -n "$PY" ]; then
  ok "Python $("$PY" --version 2>&1 | awk '{print $2}')"
elif [ -n "$FOUND_ANY_PYTHON" ]; then
  VER="$("$FOUND_ANY_PYTHON" --version 2>&1 | awk '{print $2}')"
  bad "Python $VER is too old — Gethu needs 3.11 or newer."
  note "Upgrade Python (you have $VER):
     Debian/Ubuntu:  sudo apt install python3.12 python3.12-venv
     Fedora:         sudo dnf install python3.12
     macOS:          brew install python@3.12"
  say ""
  say "${RED}Cannot continue without Python 3.11+.${RESET}"
  printf '%s\n\n' "${PROBLEMS[@]}"
  exit 1
else
  bad "No Python found at all."
  note "Install Python 3.11 or newer:
     Debian/Ubuntu:  sudo apt install python3 python3-venv
     Fedora:         sudo dnf install python3
     macOS:          brew install python"
  say ""
  say "${RED}Cannot continue without Python.${RESET}"
  printf '%s\n\n' "${PROBLEMS[@]}"
  exit 1
fi

# 3. venv module ------------------------------------------------------------
if "$PY" -c 'import venv' 2>/dev/null; then
  ok "Python venv module"
else
  bad "Python venv module is missing."
  note "Install it, then run this script again:
     Debian/Ubuntu:  sudo apt install python3-venv
     Fedora:         sudo dnf install python3-libs"
fi

# 4. Internet ---------------------------------------------------------------
# Only warn: pip may still work behind a local mirror or proxy.
# Use a HEAD-style range request so we test reachability without pulling the
# whole index page (which is tens of megabytes and times out on slow links).
if command -v curl >/dev/null 2>&1; then
  if curl -sS --max-time 8 -r 0-0 -o /dev/null https://pypi.org/simple/ 2>/dev/null; then
    ok "Internet connection"
  else
    warn "Could not reach pypi.org — pip may fail. Check your connection or proxy."
  fi
elif command -v wget >/dev/null 2>&1; then
  if wget -q --timeout=8 --tries=1 -O /dev/null https://pypi.org/simple/ 2>/dev/null; then
    ok "Internet connection"
  else
    warn "Could not reach pypi.org — pip may fail. Check your connection or proxy."
  fi
else
  warn "No curl or wget — skipping the internet check."
fi

# 5. Disk space -------------------------------------------------------------
FREE_MB=$(df -Pk . 2>/dev/null | awk 'NR==2 {print int($4/1024)}' || echo "")
if [ -n "$FREE_MB" ]; then
  if [ "$FREE_MB" -ge 500 ]; then
    ok "${FREE_MB} MB free disk space"
  else
    bad "Only ${FREE_MB} MB free — Gethu needs about 500 MB."
    note "Free up some space, then run this script again."
  fi
fi

# 6. Port ---------------------------------------------------------------
PORT="${GETHU_PORT:-8000}"
if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  warn "Port ${PORT} is already in use — Gethu will fail to start on it."
  note "Free the port, or start Gethu on another one:
     GETHU_PORT=8001 ./run.sh"
elif command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" >/dev/null 2>&1; then
  warn "Port ${PORT} is already in use — Gethu will fail to start on it."
  note "Free the port, or start Gethu on another one:
     GETHU_PORT=8001 ./run.sh"
else
  ok "Port ${PORT} is free"
fi

say ""

if [ ${#PROBLEMS[@]} -gt 0 ]; then
  say "${RED}${BOLD}Fix these first:${RESET}"
  for p in "${PROBLEMS[@]}"; do
    say ""
    say "${RED}•${RESET} $p"
  done
  say ""
  exit 1
fi

# ------------------------------------------------------------------- install
say "${BOLD}Setting up Gethu${RESET}"

if [ -d .venv ]; then
  ok "Reusing existing .venv"
else
  if ! "$PY" -m venv .venv 2>/dev/null; then
    bad "Could not create a virtual environment."
    say ""
    say "  Debian/Ubuntu:  sudo apt install python3-venv"
    say "  Fedora:         sudo dnf install python3-libs"
    say ""
    exit 1
  fi
  ok "Created .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

say "Installing dependencies (this can take a minute)…"
if ! python -m pip install --quiet --upgrade pip; then
  bad "Could not upgrade pip."
  say "  Check your internet connection (or proxy settings) and try again."
  exit 1
fi
if ! python -m pip install --quiet -r requirements.txt; then
  bad "Dependency install failed."
  say "  Check your internet connection, then run:  pip install -r requirements.txt"
  exit 1
fi
ok "Dependencies installed"

if [ -f .env ]; then
  ok ".env already exists — left untouched"
else
  cp .env.example .env
  warn "Created .env — you still need to add your Gemini API key."
fi

# --------------------------------------------------------------------- ready
say ""
NEED_KEY=1
if grep -qE '^GEMINI_API_KEY=.+' .env 2>/dev/null; then
  NEED_KEY=0
fi

if [ "$NEED_KEY" -eq 1 ]; then
  say "${BOLD}${YELLOW}Almost there — one step left: add your free Gemini API key.${RESET}"
  say ""
  say "  1. Get a key:  ${BOLD}https://aistudio.google.com/apikey${RESET}"
  say "  2. Open .env:  ${BOLD}${EDITOR:-nano} .env${RESET}"
  say "  3. Put it on the line:  ${BOLD}GEMINI_API_KEY=your_key_here${RESET}"
  say ""
  say "  Then start Gethu:  ${BOLD}./run.sh${RESET}"
else
  ok "API key detected"
  say ""
  say "${GREEN}${BOLD}Gethu is ready.${RESET}  Start it with:  ${BOLD}./run.sh${RESET}"
fi
say ""
say "${DIM}Suggested: a Chromium browser (Chrome, Edge, Brave) for voice input.${RESET}"
say "${DIM}On Linux, install speech voices with: sudo apt install speech-dispatcher espeak-ng${RESET}"
say ""
