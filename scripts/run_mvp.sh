#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
  echo 'Install uv, then run this launcher again. See README.md for setup.' >&2
  exit 1
fi
uv sync --frozen
exec uv run python scripts/run_mvp.py "$@"
