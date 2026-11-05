# CLAUDE.md — CloudDrop AI (repo root)

> These instructions OVERRIDE default behavior. When a rule here conflicts with a habit, the rule wins.

CloudDrop AI is an AI-powered cloud storage SaaS: upload, organize and share files; a background pipeline extracts text and builds embeddings; users search by meaning, ask questions about their files (RAG) and get summaries and categories.

**Greenfield — there is no legacy code.** Every rule applies from the first commit. The danger here is not copying a bad neighbour; it is *your own defaults*. The table below lists the habits that are wrong in this repo. Read it first.

Load order: this file applies everywhere. `backend/CLAUDE.md` and `frontend/CLAUDE.md` add to it. On a conflict the more specific file wins, **except** cross-boundary contracts (below), which this file owns.

---

## Defaults to override

| Your habit | The rule in this repo |
|---|---|
| Invent an endpoint, field, env var, APIM path or model name "that should exist" | **Never invent a contract.** If it is not in this repo, in `docs/`, or confirmed by the user, say what is missing and ask. |
| `async def` endpoint that calls a sync DB / boto3 / pypdf | Endpoints are plain `def` (threadpool) with the sync Session. See ADR rule in backend. |
| Stream file bytes through FastAPI | Files go browser <-> S3 by presigned URL. FastAPI never touches file bytes except in workers. |
| Trust client-sent filename, content-type, size, or S3 key | All server-derived or server-verified. See Upload protocol. |
| Pass an ORM object / big payload to a Celery task | Pass ids. Tasks are idempotent and re-read state. |
| `commit()` then `.delay()` and hope | DB is the source of truth; a sweeper re-enqueues stuck work. See backend Processing. |
| Add a library "to be safe" or because a tutorial did | Dependency bar below. A new dependency needs a stated reason. |
| Edit an applied Alembic migration, or import app models inside one | Add a new migration. Migrations are self-contained. |
| Return 200 with `{"success": false}` or swallow an exception | Accurate status + the one error shape. Never swallow. |
| Log request bodies, prompts, document text, tokens, presigned URLs | None of these ever reach a log, metric or error tracker. |
| Put document text into an LLM prompt as if it were instructions | Document text is untrusted data. See AI rules. |
| Skip tests because "it is just scaffolding" | New logic ships with a test. Auth, permissions and idempotency first. |
| Say "done" / "should work" without running anything | Run the gates; paste real output; say plainly what you did not run. |
| Create a branch, commit or push unasked | Never. The user does that. |

---

## Workflow

- **Plan first** for anything with 3+ steps or an architectural decision. Track in `tasks/todo.md` (checkable items) and add a review section when done. If it goes sideways, STOP and re-plan.
- **Subagents** for broad searches and independent research; one task per subagent.
- **Verify before done.** Backend: `ruff check`, `ruff format --check`, `mypy`, `pytest`. Frontend: `ng build`, `ng test`, `ng lint`, `npm run format`. Run them on everything you touched. **Never claim a check you didn't run**; if it failed, say so and paste the output.
- **Root causes, not patches.** Minimal diffs; touch only what the task needs. Ask "is there a more elegant way?" on non-trivial work; do not over-engineer simple fixes.
- **Only what is needed now.** No speculative endpoints, tables, settings, components, or "flexibility". A feature adds what it needs.
- **Learn from corrections.** After any correction, record the pattern in `tasks/lessons.md`; read it at session start.
- **There is no CI yet.** The gates are the ones you run locally. Never skip a hook or gate to make something pass.

---

## Decisions

### Locked (do not relitigate in a task)

| Area | Decision | Why |
|---|---|---|
| Architecture | Modular monolith, one deployable per tier | Microservices add ops cost with no measured need |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (**sync**, psycopg 3), Alembic | One session style shared by API and Celery; avoids async/sync mixing bugs |
| Data | PostgreSQL + pgvector; files in S3 (never in Postgres) | Permissions and vector search in one SQL query |
| Jobs | Celery + Redis broker; **state lives in Postgres**, not Redis | Redis is not durable |
| Frontend | Angular (standalone, signals, OnPush), strict TypeScript | Team standard |
| IDs | UUID primary keys, server-generated | No enumeration; safe in URLs |
| Time | `timestamptz`, UTC everywhere, ISO-8601 on the wire | No naive datetimes, ever |
| Auth | Short-lived access JWT (memory) + rotating refresh token in `HttpOnly` cookie | See Auth contract |
| Tooling | Python 3.12 pinned; dependencies via `uv` (`uv.lock`) | Fast, reproducible |
| Environment | No `local`/`dev`/`prod` profile files committed; config via env vars | Same as org standard |
| Local services | Native Homebrew PostgreSQL (+ pgvector) and Redis, managed with pgAdmin; Docker is optional | No Docker on the dev machine |

### Pending (do not assume — ask or leave a clearly marked TODO)

| Item | Blocks |
|---|---|
| APIM base URL, chat path, embedding path, deployment names, whether both models exist | All AI work. Verify with `scripts/check_apim.sh` first |
| Embedding model and its dimension | The `vector(N)` column. Changing it later means re-embedding everything |
| Angular version and UI approach (tokens + plain SCSS until decided; **no UI kit or Tailwind without an ADR**) | First frontend scaffold |
| Permission inheritance model (file vs folder grants) | Phase 4 — write `docs/permissions.md` before coding |
| Date display format (assumed `DD/MM/YYYY HH:mm`, 24-hour, org standard) | Frontend pipes |

Record every new architectural decision as `docs/adr/NNNN-title.md` (context, decision, consequences).

---

## Cross-boundary contracts (single source of truth)

These are owned here. Backend and frontend both mirror them. Changing one means changing both sides and their tests in the same task.

### API surface
- Base path `/api/v1`. Plural kebab-case nouns. Nested only for true ownership: `/folders/{folder_id}/files`, `/files/{file_id}/permissions`.
- `POST` create -> **201** + `Location` header + **the same body the `GET` returns**. `PUT/PATCH` -> 200 with body or 204. `DELETE` -> 204, no body.
- Every list endpoint is paginated: `?page=1&page_size=50` (max 100) returning `{items, total, page, page_size}`. No unpaged collection endpoint, ever.
- Never return an ORM model, a password hash, a token, an S3 key, or a content hash.
- Same-origin in browsers: dev uses the Angular proxy, prod uses a reverse proxy. **No hostname, port or API base is baked into a build.**

### Error shape (one, for every failure, including validation)
```json
{ "error": { "code": "file_not_found", "message": "File not found", "request_id": "…", "details": [] } }
```
`code` is a stable machine string; `message` is safe to show a user; `details` is for field-level validation (`[{ "field": "name", "message": "…" }]`). Never a stack trace, SQL, S3 key, internal id, or secret.

### Auth
- Access token: JWT, ~15 min, sent as `Authorization: Bearer`. Held **in memory only** on the client.
- Refresh token: opaque or JWT, ~7 days, **rotating with reuse detection**, stored hashed server-side, delivered as an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth`.
- `401` = unauthenticated or expired (client refreshes once, single-flight). `403` = authenticated but not allowed. **A resource the caller may not even know exists returns `404`, not `403`.**
- Login errors are generic ("invalid credentials"); never reveal whether an email exists.

### File status (wire values are exactly these strings)
```
pending_upload -> uploaded -> scanning -> processing -> ready
                               |            |
                            infected      failed        needs_ocr (no extractable text)
```
- Only `ready` files are searchable, AI-readable, shareable or downloadable by non-owners. `infected` files are never downloadable by anyone.
- Defined once as `FileStatus` (backend) and mirrored as a union type (frontend). Adding a status means updating both, the DB check, and tests.

### Upload protocol (sequence is fixed)
1. `POST /files/uploads` with `{name, size_bytes, content_type, folder_id}` -> server validates (size cap, type allow-list, quota, folder permission), creates `files` row in `pending_upload`, **generates the S3 key itself**, returns presigned POST/multipart instructions (short TTL, size-bounded).
2. Browser uploads **directly to S3**. It sends **no `Authorization` header** to S3.
3. `POST /files/{file_id}/uploads/complete` -> server calls S3 `HeadObject`, **verifies size (and ETag/checksum) against what it expects**, moves status to `uploaded`, enqueues processing. It never trusts the client's claim.
4. Pipeline runs (scan -> extract -> chunk -> embed). Client polls status (or subscribes) until a terminal state.

### Download
Permission check -> status check (`ready`, or owner of a non-infected file) -> short-lived presigned GET (`Content-Disposition` with a sanitized filename). The URL is never logged, stored, or put in analytics.

### Roles
`owner > editor > viewer`. All checks go through one function on the backend (`can_access`); the frontend only *reflects* what the server returned. Search and RAG filter by permission **in the same SQL query**.

### Embeddings
One constant (`EMBEDDING_DIM`) and one model name, stored on every embedding row (`model`, `dim`). Query and documents must use the same model. Migrations hard-code the number; they never import app code.

---

## Security baseline (both tiers)

- **The server decides, the client reflects.** Hiding a button is not authorization.
- No secrets in git, in the Angular bundle, or in logs. `.env` is git-ignored; `.env.example` has no real values.
- Uploaded files and document text are **untrusted input**: type and size are verified server-side, never rendered as HTML, scanned before use.
- Least privilege on cloud credentials: the S3 IAM identity can only touch this bucket's prefixes; the bucket blocks all public access; CORS allows only the app origin and exposes `ETag`.
- Rate-limit auth endpoints and AI endpoints per user and per IP.
- PII-bearing content (document text, prompts, completions, file names) is treated like PHI in the org standard: **never in logs, metrics, error trackers, URLs, `localStorage`, or analytics.**

## Dependencies

Every dependency is a permanent cost (CVEs, upgrades, size, startup). In order: can the language/framework/standard library do it? Is it already installed? Can ~20 lines do it? Only then add one — with a stated reason, a permissive licence, and an active maintainer. One library per job. Prune when the last import goes. Never add a package "for later".

## Commands (from repo root)

```bash
cp .env.example .env                 # then set POSTGRES_PASSWORD (keep DATABASE_URL in sync)
docker compose up -d                 # postgres+pgvector, redis
bash scripts/check_apim.sh           # verify the AI gateway (needs APIM values in .env)
```
Backend and frontend commands live in their own files.

## Git

`main` (protected) <- `develop` <- `feat/*` · `fix/*` · `refactor/*` · `docs/*` · `chore/*`. PRs target `develop`; squash merge; delete the branch.
[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): short description`, imperative, subject <= 72 chars.

- **Never create a branch, commit, or push on your own.** Make the requested edits and stop.
- **Never add a `Co-Authored-By` trailer and never commit as an AI user.** (Org standard; remove this line only if the owner says so.)
- Formatting-only changes go in their own commit. Never commit `.env`, keys, dumps, or build output.

## PR gate (root)

- [ ] No invented contract: every endpoint/field/env var exists in code or docs
- [ ] Cross-boundary contract change updated on **both** sides, with tests
- [ ] No secret, token, presigned URL, prompt or document text in code, logs or fixtures
- [ ] New logic has tests; all gates run and the real output reported
- [ ] New dependency (if any) justified in the PR
- [ ] ADR added for any architectural decision
