#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
checker="$repo_root/scripts/check-docs-drift.py"
readme="$repo_root/README.md"
backup=$(mktemp)
cp "$readme" "$backup"
trap 'cp "$backup" "$readme"; rm -f "$backup"' EXIT

uv run --project "$repo_root/backend" python "$checker" >/dev/null

python - "$readme" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
needle = "    agent --> llm"
assert needle in text
path.write_text(text.replace(needle, "    agent --> obs", 1), encoding="utf-8")
PY

if uv run --project "$repo_root/backend" python "$checker" >/dev/null 2>&1; then
  printf 'checker accepted a drifted import graph\n' >&2
  exit 1
fi

uv run --project "$repo_root/backend" python "$checker" --fix >/dev/null
uv run --project "$repo_root/backend" python "$checker" >/dev/null
