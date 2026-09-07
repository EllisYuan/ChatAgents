#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
probe="$repo_root/backend/src/chat_agents/llm/_architecture_probe.py"
output=$(mktemp)
trap 'rm -f "$probe" "$output"' EXIT

uv run --project "$repo_root/backend" lint-imports --config "$repo_root/backend/pyproject.toml" --no-cache >/dev/null
printf 'from ..agent import events\n' >"$probe"

if uv run --project "$repo_root/backend" lint-imports --config "$repo_root/backend/pyproject.toml" --no-cache >"$output" 2>&1; then
  printf 'Import Linter accepted llm -> agent forbidden dependency\n' >&2
  exit 1
fi

grep -q 'LLM 模块保持为共享叶子 BROKEN' "$output"
