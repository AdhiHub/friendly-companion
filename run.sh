#!/usr/bin/env bash
# Start Gethu (Linux / macOS). Runs setup automatically if needed.

set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run — setting up Gethu…"
  bash setup.sh
fi

# shellcheck disable=SC1091
source .venv/bin/activate

HOST="${GETHU_HOST:-127.0.0.1}"
PORT="${GETHU_PORT:-8000}"

echo ""
echo "  Gethu is starting…"
echo "  Open:  http://${HOST}:${PORT}"
echo "  Stop:  Ctrl + C"
echo ""

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
