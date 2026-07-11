#!/bin/zsh
# Refresh pending Workflows, matching Final-mail comments, and the Google Sheets workbook.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "Python environment not found: $PYTHON_BIN"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  print -u2 "Configuration file not found: $ENV_FILE"
  exit 1
fi

dotenv_value() {
  "$PYTHON_BIN" -c '
from dotenv import dotenv_values
import sys
print(dotenv_values(sys.argv[1]).get(sys.argv[2], ""))
' "$ENV_FILE" "$1"
}

SPREADSHEET_ID="${GOOGLE_SPREADSHEET_ID:-$(dotenv_value GOOGLE_SPREADSHEET_ID)}"
SHEET_PREFIX="${GOOGLE_SHEET_PREFIX:-$(dotenv_value GOOGLE_SHEET_PREFIX)}"
SHEET_PREFIX="${SHEET_PREFIX:-WF}"

if [[ -z "$SPREADSHEET_ID" ]]; then
  print -u2 "Set GOOGLE_SPREADSHEET_ID in $ENV_FILE before running this update."
  exit 1
fi

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" main.py google-sheet-update \
  --spreadsheet-id "$SPREADSHEET_ID" \
  --sheet-name "$SHEET_PREFIX"
