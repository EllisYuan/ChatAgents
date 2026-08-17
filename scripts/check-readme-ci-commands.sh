#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readme="$repo_root/README.md"
workflow="$repo_root/.github/workflows/ci.yml"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

awk '
  /^```bash[[:space:]]+ci-command[[:space:]]*$/ { in_block = 1; found = 1; next }
  /^```/ { in_block = 0; next }
  in_block {
    if ($0 != "" && $0 !~ /^#/) print
  }
  END { if (!found) exit 2 }
' "$readme" >"$tmp_dir/readme-commands"

awk '
  /^[[:space:]]*run:[[:space:]]+/ {
    sub(/^[[:space:]]*run:[[:space:]]+/, "")
    print
  }
' "$workflow" >"$tmp_dir/workflow-commands"

if [[ ! -s "$tmp_dir/readme-commands" ]]; then
  printf 'README has no ci-command entries\n' >&2
  exit 1
fi

while IFS= read -r command; do
  if ! grep -F -x -q -- "$command" "$tmp_dir/workflow-commands"; then
    printf 'README command is missing from %s: %s\n' "$workflow" "$command" >&2
    exit 1
  fi
done <"$tmp_dir/readme-commands"

printf 'README ci-command entries match %s\n' "$workflow"
