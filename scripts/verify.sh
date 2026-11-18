#!/usr/bin/env bash
# The same gates CI runs, in one command. Usage: scripts/verify.sh [backend|frontend]
set -euo pipefail
cd "$(dirname "$0")/.."
what="${1:-all}"

if [[ "$what" == all || "$what" == backend ]]; then
  (cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q)
fi
if [[ "$what" == all || "$what" == frontend ]]; then
  (cd frontend && npm run format:check && npm run lint && npm test && npm run build)
fi
