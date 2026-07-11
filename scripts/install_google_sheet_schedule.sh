#!/bin/zsh
# Install or replace the current user's weekday 10:00 Google Sheets update schedule.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.aconex.google-sheet-update"
TEMPLATE="$PROJECT_ROOT/scripts/$LABEL.plist.template"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
USER_DOMAIN="gui/$(id -u)"

if [[ ! -f "$TEMPLATE" ]]; then
  print -u2 "LaunchAgent template not found: $TEMPLATE"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_ROOT/logs"
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$TEMPLATE" > "$TARGET"

launchctl bootout "$USER_DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$USER_DOMAIN" "$TARGET"
print "Installed $LABEL: weekdays at 10:00 local time."
print "Logs: $PROJECT_ROOT/logs/google_sheet_update.log"
