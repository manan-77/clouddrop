# CloudDrop AI

AI-powered cloud storage: upload, organize, share, and search files by meaning.

Status: backend foundation, authentication and file storage are built, and the Angular app shell is scaffolded (theme, error handling, shared UI). Sign-in and the file explorer, sharing, the processing pipeline and the AI features are planned. See `tasks/todo.md` for the full plan and `docs/` for the architecture.

## Layout
- `backend/` FastAPI, SQLAlchemy 2 (sync), Alembic, Celery (planned)
- `frontend/` Angular 21
- `infra/` database init and deployment config
- `docs/` ER diagram, API reference, architecture decision records
- `tasks/` task plan and lessons learned
- `CLAUDE.md` files hold the engineering standards for every tier

## Local setup
Needs PostgreSQL 17 with the pgvector extension, Redis, Python 3.12 and [uv](https://docs.astral.sh/uv/). Docker is optional (`docker-compose.yml`).

1. `cp .env.example .env` and fill it in. `JWT_SECRET` must be 32+ characters.
2. Create the databases (the vector extension is created once by a superuser):
   - `createdb clouddrop` then `psql clouddrop -c 'CREATE EXTENSION IF NOT EXISTS vector;'`
   - `createdb clouddrop_test` (the tests rebuild it from the migrations)
3. Backend, from `backend/`:
   - `uv sync`
   - `uv run alembic upgrade head`
   - `uv run uvicorn app.main:app --reload` (docs at `http://localhost:8000/docs`)
4. File uploads need an S3 bucket (`S3_BUCKET` and AWS credentials in `.env`). Without one, the file endpoints return 503 `storage_not_configured`.
5. AI features need the Azure APIM details; verify them with `bash scripts/check_apim.sh`.

## Checks
Backend, from `backend/`: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`.

Frontend, from `frontend/` (after `npm install`): `npm run lint`, `npm run format:check`, `npm run build`, `npm test`. Run the app with `npm start` (port 4200; it proxies the API on port 8000, so start the backend too).

## Branches and pull requests
`main` (protected) <- `develop` <- `feat/*` | `fix/*` | `docs/*` | `chore/*` | `refactor/*`. Every change goes through a pull request into `develop`, is reviewed against the CLAUDE.md standards, and is squash merged; the branch is then deleted. Commits follow Conventional Commits: `type(scope): description`.
