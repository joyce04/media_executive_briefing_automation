#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): auto-format edited Python files with ruff.
# Walks up to the nearest pyproject.toml so it runs against the right venv.
set -euo pipefail

payload="$(cat)"
file_path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"

[ -z "$file_path" ] && exit 0
case "$file_path" in *.py) ;; *) exit 0 ;; esac
[ ! -f "$file_path" ] && exit 0

dir="$(dirname "$file_path")"
project_root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/pyproject.toml" ]; then
    project_root="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done
[ -z "$project_root" ] && exit 0

cd "$project_root"
[ ! -d ".venv" ] && exit 0

uv run ruff check --fix "$file_path" >/dev/null 2>&1 || true
uv run ruff format "$file_path" >/dev/null 2>&1 || true
