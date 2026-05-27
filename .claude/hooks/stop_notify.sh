#!/usr/bin/env bash
# Stop hook: post a macOS notification when Claude finishes a turn.
set -euo pipefail

if command -v osascript >/dev/null 2>&1; then
  osascript -e 'display notification "Claude finished a turn" with title "kfa_daily_media_intel" sound name "Glass"' \
    >/dev/null 2>&1 || true
fi
