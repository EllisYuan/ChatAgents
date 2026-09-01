.PHONY: setup db test contract lint typecheck build docs check

setup db test contract lint typecheck build docs check:
	uv run --project backend python scripts/dev.py $@
