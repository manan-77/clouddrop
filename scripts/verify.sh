#!/usr/bin/env bash
# The same gates CI runs, in one command. Usage: scripts/verify.sh [backend|frontend]
set -euo pipefail
cd "$(dirname "$0")/.."
what="${1:-all}"

if [[ "$what" == all || "$what" == backend ]]; then
  (cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q)
  # What the production image runs: the app must import with runtime dependencies only. Tests and
  # type checks install the dev group too, so a package missing from `dependencies` hides there.
  (cd backend && DATABASE_URL=postgresql+psycopg://u:p@localhost/db \
    JWT_SECRET=ci-only-secret-ci-only-secret-ci-only-secret \
    uv run --isolated --no-dev python -c "import app.main, app.worker.celery_app")
fi
if [[ "$what" == all || "$what" == frontend ]]; then
  (cd frontend && npm run format:check && npm run lint && npm test && npm run build)
fi
