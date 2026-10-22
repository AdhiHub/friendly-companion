#!/usr/bin/env bash
# Start Friendly Companion (Linux / macOS). Runs setup automatically if needed.

set -euo pipefail

cd "$(dirname "$0")"

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'

# --- make sure the app is set up -------------------------------------------------
if [ ! -d .venv ]; then
  echo "First run — setting up Friendly Companion…"
  echo ""
  bash setup.sh
fi

# A .venv can exist but be broken (interrupted install, moved folder).
if [ ! -x .venv/bin/python ]; then
  echo "${RED}✗${RESET} The Python environment looks broken."
  echo "  Fix it by running:  ${BOLD}rm -rf .venv && ./setup.sh${RESET}"
  exit 1
fi

if [ ! -f .env ]; then
  echo "${YELLOW}!${RESET} No .env yet — creating one from the example."
  cp .env.example .env
fi

if ! grep -qE '^GEMINI_API_KEY=.+' .env 2>/dev/null; then
  echo "${YELLOW}!${RESET} No Gemini API key is set, so Friendly Companion can't reply yet."
  echo ""
  echo "  1. Get a free key:  ${BOLD}https://aistudio.google.com/apikey${RESET}"
  echo "  2. Put it in .env:  ${BOLD}GEMINI_API_KEY=your_key_here${RESET}"
  echo ""
  echo "  Starting anyway — the UI will open, but replies will fail."
  echo ""
fi

# shellcheck disable=SC1091
source .venv/bin/activate

HOST="${COMPANION_HOST:-127.0.0.1}"
PORT="${COMPANION_PORT:-8000}"

# --- warn early if the port is taken ---------------------------------------------
if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  echo "${RED}✗${RESET} Port ${PORT} is already in use."
  echo "  Start on a different one:  ${BOLD}COMPANION_PORT=8001 ./run.sh${RESET}"
  exit 1
elif command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" >/dev/null 2>&1; then
  echo "${RED}✗${RESET} Port ${PORT} is already in use."
  echo "  Start on a different one:  ${BOLD}COMPANION_PORT=8001 ./run.sh${RESET}"
  exit 1
fi

echo ""
echo "  ${GREEN}${BOLD}Friendly Companion is starting…${RESET}"
echo "  Open:  http://${HOST}:${PORT}"
echo "  Stop:  Ctrl + C"
echo ""
echo "  ${DIM}If the browser shows an old version, press Ctrl + Shift + R.${RESET}"
echo ""

# Open the browser automatically so setup can be finished in the web UI.
if [ "${COMPANION_NO_BROWSER:-0}" != "1" ]; then
  if command -v xdg-open >/dev/null 2>&1; then
    ( sleep 2; xdg-open "http://${HOST}:${PORT}" >/dev/null 2>&1 & ) || true
  elif command -v open >/dev/null 2>&1; then
    ( sleep 2; open "http://${HOST}:${PORT}" >/dev/null 2>&1 & ) || true
  fi
fi

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
