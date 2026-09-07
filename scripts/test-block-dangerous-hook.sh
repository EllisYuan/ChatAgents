#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
hook="$repo_root/.claude/hooks/block-dangerous.sh"

printf '%s' '{"tool_input":{"command":"git status"}}' | "$hook" >/dev/null

set +e
output=$(printf '%s' '{"tool_input":{"command":"git reset --hard HEAD~1"}}' | "$hook")
status=$?
set -e

if [[ $status -ne 2 ]] || [[ "$output" != *'permissionDecision":"deny"'* ]]; then
  printf 'dangerous-command hook did not deny git reset --hard\n' >&2
  exit 1
fi
