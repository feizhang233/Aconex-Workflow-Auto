#!/usr/bin/env bash
# Install or replace a weekday 10:00 cron job for the Aconex daily-update pipeline.
# Target: Ubuntu (or other Linux) VPS with cron installed.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$PROJECT_ROOT/scripts/run_daily_update.sh"
LOG_DIR="$PROJECT_ROOT/logs"
STDOUT_LOG="$LOG_DIR/daily_update.log"
STDERR_LOG="$LOG_DIR/daily_update.error.log"
MARKER="# aconex-daily-update"
CRON_SCHEDULE="0 10 * * 1-5"
CRON_LINE="${CRON_SCHEDULE} ${RUNNER} >>${STDOUT_LOG} 2>>${STDERR_LOG} ${MARKER}"

if [[ ! -x "$RUNNER" ]]; then
  chmod +x "$RUNNER"
fi

if [[ ! -x "$RUNNER" ]]; then
  echo "Runner is not executable: $RUNNER" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

# Keep every other crontab entry; replace any previous aconex-daily-update line.
EXISTING="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "$EXISTING" | grep -vF "$MARKER" || true)"
{
  [[ -n "$FILTERED" ]] && printf '%s\n' "$FILTERED"
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "Installed weekday cron job: Mon–Fri 10:00 (server local time)"
echo "Command: $RUNNER"
echo "Stdout:  $STDOUT_LOG"
echo "Stderr:  $STDERR_LOG"
echo
echo "Current aconex cron entries:"
crontab -l | grep -F "$MARKER" || true
echo
echo "Manual run:  $RUNNER"
echo "Remove job:  crontab -l | grep -vF '$MARKER' | crontab -"
echo "Tip: set the VPS timezone to Belgrade so 10:00 is Europe/Belgrade local time:"
echo "  sudo timedatectl set-timezone Europe/Belgrade"
