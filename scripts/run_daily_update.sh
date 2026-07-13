#!/usr/bin/env bash
# Weekday daily pipeline for Ubuntu VPS:
#   1. Aconex API → SQLite + weekly manifest (new/changed Workflows)
#   2. Triggered 72-hour Final Mail scan → SQLite + manifest comments
#   3. Unsynced manifest entries → Google Sheets and DocFlow

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
ENV_FILE="$PROJECT_ROOT/.env"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python environment not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Configuration file not found: $ENV_FILE" >&2
  exit 1
fi

dotenv_value() {
  "$PYTHON_BIN" -c '
from dotenv import dotenv_values
import sys
print(dotenv_values(sys.argv[1]).get(sys.argv[2], "") or "")
' "$ENV_FILE" "$1"
}

SPREADSHEET_ID="${GOOGLE_SPREADSHEET_ID:-$(dotenv_value GOOGLE_SPREADSHEET_ID)}"
SHEET_PREFIX="${GOOGLE_SHEET_PREFIX:-$(dotenv_value GOOGLE_SHEET_PREFIX)}"
SHEET_PREFIX="${SHEET_PREFIX:-WF}"

if [[ -z "$SPREADSHEET_ID" ]]; then
  echo "Set GOOGLE_SPREADSHEET_ID in $ENV_FILE before running this update." >&2
  exit 1
fi

cd "$PROJECT_ROOT"
echo "$(date '+%Y-%m-%d %H:%M:%S') starting daily-update"
exec "$PYTHON_BIN" main.py daily-update \
  --spreadsheet-id "$SPREADSHEET_ID" \
  --sheet-name "$SHEET_PREFIX"
