#!/usr/bin/env bash
# PreToolUse hook (Bash): refuse `git commit` if staged diff contains secret-like strings.
set -euo pipefail

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')"

# Only act on git commit invocations.
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Patterns that suggest real secrets, not placeholders.
patterns='sk-or-v1-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|SMTP_PASSWORD=[^[:space:]"'"'"']{8,}|OPENROUTER_API_KEY=sk-[^[:space:]"'"'"']{8,}|ANTHROPIC_API_KEY=sk-[^[:space:]"'"'"']{8,}'

if git diff --cached --no-color | grep -E -- "$patterns" >/dev/null 2>&1; then
  echo "::commit blocked — staged diff contains a secret-like string." >&2
  echo "Matched on one of: sk-or-v1-*, sk-ant-*, SMTP_PASSWORD=*, OPENROUTER_API_KEY=sk-*, ANTHROPIC_API_KEY=sk-*" >&2
  echo "Run: git diff --cached | grep -E '$patterns'" >&2
  exit 2
fi
