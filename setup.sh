#!/usr/bin/env bash
# Gethu one-command setup for Linux / macOS.
# Creates a virtual environment, installs dependencies and prepares .env.

set -euo pipefail

cd "$(dirname "$0")"

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s\n' "${GREEN}✓${RESET} $*"; }
warn() { printf '%s\n' "${YELLOW}!${RESET} $*"; }
die()  { printf '%s\n' "${RED}✗${RESET} $*" >&2; exit 1; }

say "${BOLD}Gethu setup${RESET}"
say ""

# 1. Find a suitable Python -----------------------------------------------------
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done
[ -n "$PY" ] || die "Python 3.11+ not found. Install it, then run this again.
   Debian/Ubuntu:  sudo apt install python3 python3-venv
   macOS:          brew install python"
ok "Using $("$PY" --version 2>&1)"

# 2. Virtual environment --------------------------------------------------------
if [ -d .venv ]; then
  ok "Reusing existing .venv"
else
  if ! "$PY" -m venv .venv 2>/dev/null; then
    die "Could not create a virtual environment.
   Debian/Ubuntu:  sudo apt install python3-venv"
  fi
  ok "Created .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# 3. Dependencies ---------------------------------------------------------------
say "Installing dependencies (this can take a minute)…"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
ok "Dependencies installed"

# 4. .env -----------------------------------------------------------------------
if [ -f .env ]; then
  ok ".env already exists — left untouched"
else
  cp .env.example .env
  warn "Created .env — you must add your Gemini API key."
fi

if ! grep -qE '^GEMINI_API_KEY=.+' .env 2>/dev/null; then
  say ""
  say "${BOLD}One step left:${RESET} add your free Gemini API key."
  say "  1. Get a key:  ${BOLD}https://aistudio.google.com/apikey${RESET}"
  say "  2. Edit .env:  ${BOLD}${EDITOR:-nano} .env${RESET}"
  say "  3. Put it on the line:  GEMINI_API_KEY=your_key_here"
  say ""
  say "Then start Gethu with:  ${BOLD}./run.sh${RESET}"
else
  say ""
  ok "API key detected. Start Gethu with: ${BOLD}./run.sh${RESET}"
fi
