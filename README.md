# CloudDrop AI

AI-powered cloud storage: upload, organize, share, and search files by meaning.

## Layout
- `backend/` FastAPI + SQLAlchemy + Celery
- `frontend/` Angular
- `infra/` Docker and deployment config
- `docs/` architecture, ER diagram, API design

## Local start
1. `cp .env.example .env`; set `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`
2. Local Postgres (with the `vector` extension) and Redis running via Homebrew. Create the DB:
   `createdb clouddrop` then `psql clouddrop -c 'CREATE EXTENSION IF NOT EXISTS vector;'`
   (Docker alternative: `docker compose up -d`)
3. `bash scripts/check_apim.sh` once the APIM values are in `.env`

## Branches
`main` (protected) <- `develop` <- `feat/*` | `fix/*` | `refactor/*`. PRs target `develop`, squash merge.
Commits follow Conventional Commits: `type(scope): description`.
