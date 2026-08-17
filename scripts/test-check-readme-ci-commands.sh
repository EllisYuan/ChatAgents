#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
checker="$repo_root/scripts/check-readme-ci-commands.sh"

if [[ ! -x "$checker" ]]; then
  printf 'checker is missing or not executable: %s\n' "$checker" >&2
  exit 1
fi

bash "$checker" >/dev/null

readme_backup=$(mktemp)
trap 'mv "$readme_backup" "$repo_root/README.md"' EXIT
cp "$repo_root/README.md" "$readme_backup"

python - "$repo_root/README.md" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
needle = "uv run --project backend mypy --config-file=backend/pyproject.toml backend"
assert needle in text
path.write_text(text.replace(needle, "uv run --project backend mypy --config-file=backend/pyproject.toml backend --drift", 1))
PY

if bash "$checker" >/dev/null 2>&1; then
  printf 'checker accepted a drifted README command\n' >&2
  exit 1
fi

printf 'command consistency checker tests passed\n'
