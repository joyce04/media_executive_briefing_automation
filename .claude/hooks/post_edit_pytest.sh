#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): run unit tests after a .py edit.
# Walks up from the edited file to find the enclosing pyproject.toml so it
# Does The Right Thing when the user has multiple projects on disk (e.g. an
# original + a sibling fork). Reports failures as a non-blocking warning -
# pre-existing test failures should not jam the agent loop.
set -euo pipefail

payload="$(cat)"
file_path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"

case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac
case "$file_path" in
  *"/agents/"*|*"/pipeline/"*|*"/collectors/"*|*"/database/"*|*"/models/"*|*"/reports/"*|*"/scripts/"*|*"/tests/"*) ;;
  *) exit 0 ;;
esac

# Walk up to find pyproject.toml
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
[ ! -d "$project_root/tests/unit" ] && exit 0

cd "$project_root"

# Only run if a .venv exists; never block on missing setup.
if [ ! -d ".venv" ]; then
  exit 0
fi

# Run tests; downgrade failures to warnings (exit 1 = visible but non-blocking).
out="$(uv run pytest tests/unit/ -x --quiet --no-header 2>&1 || true)"
if printf '%s\n' "$out" | grep -qE '(failed|error)'; then
  printf '%s\n' "$out" | tail -15 >&2
  echo "::warning: tests not green in $project_root - inspect above" >&2
  exit 1
fi
