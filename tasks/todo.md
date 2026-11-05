# Tasks

## Phase 0 — Setup
- [x] Repo layout, CLAUDE.md files, .env.example, .gitignore, compose, README
- [x] Local Postgres 17 + pgvector 0.8.7 on :5432, Redis running, `clouddrop` DB
- [ ] APIM check (`scripts/check_apim.sh`) — waiting on APIM values
- [ ] First commit + `develop` branch — user does this

## Phase 1 — Backend foundation + auth  (DONE)
- [x] uv project (Python 3.12), deps, ruff/mypy/pytest config
- [x] core: settings, errors + handlers, request-id logging, security (argon2, JWT)
- [x] db: naming convention, sync session
- [x] auth module: users + refresh_tokens, register/login/refresh/logout/me
- [x] Alembic 0001 (reviewed): users, refresh_tokens — applied to `clouddrop`
- [x] tests on real Postgres `clouddrop_test`: 23 passing
- [x] gates: ruff, mypy strict, pytest

Review: refresh tokens are opaque, hashed, rotating, family revoked on reuse.
Deferred on purpose: auth rate limiting (Redis, Phase 8), vector tables (Phase 6, needs embedding dim),
workspaces (Phase 2), CSRF header check on /auth/refresh (SameSite=Strict only for now).
Known: starlette TestClient warns that httpx is deprecated in favour of httpx2 — revisit on upgrade.

## Phase 2 — Workspaces, folders, files, S3 upload (DONE, tested against fake S3)
- [x] boto3 (+ stubs, moto dev); settings for S3 and upload limits
- [x] workspaces (personal workspace created in the same transaction as register), sharing (`can_access`, owner-only)
- [x] storage: folders, files, file_versions; presigned POST upload (exact size + type), complete (HeadObject verify), download, soft delete
- [x] Alembic 0002 (reviewed, with workspace backfill) applied to `clouddrop`
- [x] 54 tests pass: upload protocol, size mismatch, stranger gets 404 everywhere, pagination, soft delete, query count
- [x] gates: ruff, mypy strict, pytest

NOT verified against real AWS: needs bucket + keys in .env (S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY),
bucket CORS (POST from the app origin, expose ETag), Block Public Access, default encryption.
Deferred: multipart upload for large files, folder moves, quotas, magic-byte type check (worker), purge task for soft-deleted files.

## Phase 3 — Angular frontend v1 (NEXT)
