# CloudDrop AI - Master Task Plan

Last updated: 2026-11-06. This file is the single source of truth for what is done, what is next, and what is blocked.
It contains tasks only. No code lives here.

## 0. Legend

- [x] done and merged or verified
- [~] in progress
- [ ] not started
- OK-NOW: can be built and tested without anything from the owner (fakes and local services are enough)
- NEEDS-YOU: needs a decision, credential or action from the owner
- BLOCKED-AWS: real verification needs the AWS bucket and keys
- BLOCKED-APIM: real verification needs the Azure APIM gateway details
- DECISION: an architectural choice that must be recorded as an ADR in docs/adr before coding

## 1. Working agreement (applies to every branch)

### 1.1 Branch lifecycle
1. Sync develop. Create a branch named feat/..., fix/..., docs/..., chore/... or refactor/... from develop.
2. Add or update the tasks for this branch in this file BEFORE writing code.
3. Build in small Conventional Commits. No Claude trailer. Commit identity is manan-77 (repo-local config).
4. Run every gate for the tier(s) touched and keep the real output:
   - Backend: ruff check, ruff format check, mypy strict, pytest.
   - Frontend: build, test, lint, format.
5. Push and open a PR into develop as the manan-77 account. Confirm the active GitHub account first, every time.
6. PR review against our CLAUDE.md files (see 1.3).
7. Fix every blocker and major finding, re-run the gates, push.
8. Squash merge, delete the remote branch and the local branch, switch to develop and pull.
9. Tick the boxes in this file as part of the same PR, not after the merge.

### 1.2 Definition of done for a branch
- All gates green with output shown in the PR.
- New logic has tests. Auth, permissions and idempotency are tested first.
- Migrations (if any) were read by hand, are reversible and self-contained.
- No secret, token, presigned URL, prompt or document text in code, logs, fixtures or the PR.
- Anything not verified (for example real AWS) is stated plainly in the PR.
- The PR checklist from the relevant CLAUDE.md is ticked item by item.

### 1.3 PR review rules
- The reviewer is an independent agent that receives the diff, the changed files and the PR gate checklists from the root, backend and frontend CLAUDE.md files. It does not receive my conclusions.
- Findings are classed as blocker, major or minor.
- Merge only when no blocker or major is open. Minor findings are fixed or logged in section 12.
- If a gate fails or a blocker cannot be fixed, stop and report. Never merge a red PR. Never force-push.
- A review by the same AI that wrote the code is biased. A human look from the owner is still the real safety net.

### 1.4 Release rule
- develop goes into main only through a separate release PR. Ask the owner before opening each one. main stays protected.

## 2. Status snapshot

- [x] Phase 0: repo layout, CLAUDE.md files (root, backend, frontend), env template, ignore rules, compose file, README, local Postgres 17 with pgvector 0.8.7, local Redis, uv, database and test database.
- [ ] Phase 0 leftover: APIM check script run (BLOCKED-APIM, needs values).
- [x] Phase 1: backend foundation and auth (23 tests).
- [x] Phase 2: workspaces, folders, files, file versions, S3 presigned upload and download, tested with a fake S3 (54 tests total).
- [x] PR number 1 and PR number 2 (review fixes) are squash merged into develop and their branches are deleted.
- [~] Phase 3 to Phase 8 below. Pre-work branch chore/env-template-and-docs is in review.

## 3. Inputs needed from the owner

### 3.1 AWS (needed for real file uploads) - NEEDS-YOU
- [ ] AWS account and region to use.
- [ ] An S3 bucket name (private).
- [ ] An IAM user or role restricted to that one bucket, with access key id and secret.
- [ ] Bucket settings applied: Block Public Access on, default encryption on, CORS allowing browser POST from the app origin and exposing the ETag header, lifecycle rule to expire unfinished multipart uploads.
- [ ] Values placed in the local .env file only. Never in git, never in chat.

### 3.2 Azure APIM and models (needed for all AI work) - NEEDS-YOU
- [ ] APIM base URL.
- [ ] Subscription key.
- [ ] Chat endpoint path and the deployment or model name behind it.
- [ ] Embedding endpoint path, deployment name and the embedding dimension it returns.
- [ ] Confirmation that both a chat model and an embedding model exist behind the gateway.
- [ ] Rate limits or quotas the gateway enforces.
- [ ] Values placed in the local .env file only.

### 3.3 Decisions - DECISION
- [x] Angular version pinned to 21.2 (ADR 0004) and the no-UI-kit default confirmed by default (ADR 0005). Owner may revisit.
- [ ] Embedding model: Azure endpoint or a local sentence-transformers model (fixes the vector size forever).
- [ ] Permission inheritance model for folders and files (Phase 4).
- [ ] Display date format (assumed day/month/year with 24-hour time).
- [ ] Whether email features (verification, password reset, share invitations) are in scope, and which provider.
- [ ] Whether Google sign-in is in scope.
- [ ] Hosting target confirmation (Azure Container Apps assumed) and whether a deployment is in scope at all.

### 3.4 Owner housekeeping - NEEDS-YOU
- [ ] Change the local database password from the placeholder to a real one (and update DATABASE_URL to match).
- [ ] Optionally enable branch protection on main in GitHub (require a pull request).
- [ ] Keep the MacBook awake while work runs unattended (charger plugged in, sleep prevented). The lid must stay open.
- [ ] Install ClamAV locally before Phase 5 real scanning (OK-NOW work uses a fake scanner).

## 4. Order of execution given the blockers

1. Pre-work: review and squash-merge PR number 1. OK-NOW.
2. Phase 3 (Angular app). Mostly OK-NOW. Real upload from the browser needs AWS.
3. Phase 4 (sharing and permissions). Fully OK-NOW.
4. Phase 5 (processing pipeline). OK-NOW with a fake scanner, fake S3 and real local Redis. Real ClamAV and real S3 later.
5. Phase 6 and Phase 7 (AI). Build against a fake gateway first (OK-NOW). Real verification is BLOCKED-APIM.
6. Phase 8 (hardening and deploy). Partly OK-NOW (CI, rate limiting, containers). Cloud deploy needs the owner.

Unblocked work to do first if the owner is away: pre-work, then Phase 3, then Phase 4, then Phase 5 with fakes, then the fake-gateway parts of Phase 6 and 7.

## 5. Pre-work

### Branch: none (PR number 1 already exists)
- [x] Run the independent review of PR number 1 against the root and backend CLAUDE.md PR gates.
- [x] Record findings by severity in the PR.
- [x] Fix blockers and majors on the same branch, re-run ruff, mypy and pytest, push. (Quota, folder row locks, health schema, fail-closed environment, explicit status codes, request id on 500, presign-before-commit, page bound, S3 settings. Rate limiting accepted and deferred to Phase 8.)
- [x] Squash merge into develop, delete the remote and local branch, pull develop.
- [x] Tick Phase 1 and Phase 2 items here as merged.

### Branch: chore/env-template-and-docs (small, right after the merge)
- [x] Add the new S3 and upload settings to the env template (bucket, region, endpoint override, max upload size, allowed types, presigned lifetimes) with placeholder values only.
- [x] Write ADR 0001: synchronous SQLAlchemy and plain def endpoints.
- [x] Write ADR 0002: uv and Python 3.12 pinned.
- [x] Write ADR 0003: local Postgres 17 with pgvector instead of Docker for development.
- [x] Write the ER diagram of the current schema in docs.
- [x] Write the API endpoint list of the current endpoints in docs.
- [x] Update the README local-start section to match reality.

## 6. Phase 3 - Angular frontend v1

Goal: a person can register, sign in, browse folders, upload, download and manage files in a browser.

### 6.1 Branch: feat/frontend-scaffold (OK-NOW, needs the Angular version decision)
- [x] Create the Angular workspace inside the frontend folder: standalone components, strict TypeScript, routing, SCSS.
- [x] Wire Vitest for unit tests, ESLint and Prettier. Prove all four gates run.
- [x] Add the dev proxy so the browser talks to the backend on the same origin, with no hostname baked into the build.
- [x] Create design tokens as CSS custom properties: colours, spacing, radii, typography, elevation.
- [x] Light and dark themes controlled in exactly one place, following the system setting by default.
- [x] App shell: header, sidebar, content area, responsive down to phone width.
- [x] Global error handler and a one-place error message resolver that maps the API error code to user-safe text.
- [x] Shared pipes: file size, date and time in the single agreed format.
- [x] Shared presentational pieces: button with in-flight spinner, loading skeleton, empty state, error state with retry, inline field error.
- [x] Lazy routes only. Bundle budgets set.
- [x] Accessibility baseline: visible focus, skip link, landmarks (automated accessibility checks are not set up yet).
- [x] Update the frontend CLAUDE.md with the pinned version and the real commands.
- [x] Tests: error resolver, pipes, theme switching.

### 6.2 Branch: feat/frontend-auth (OK-NOW)
- [x] Typed API client layer: one client per resource, generics on every call, wire types mirrored from the backend including the file status union.
- [x] Session store using signals. Access token kept in memory only.
- [x] Auth interceptor attaches the token only to same-origin API calls. It must never attach it to the S3 upload address.
- [x] Single-flight refresh on 401: concurrent failures wait on one refresh, the original call is retried once, a failed refresh logs the user out.
- [x] Silent session restore on page load using the refresh cookie.
- [x] Pages: sign in, register, with typed reactive forms and inline validation that mirrors the server rules (email format, password length 12 to 128, name length).
- [x] Guards: authenticated, and guest-only for the auth pages.
- [x] Logout clears every in-memory store.
- [x] Every write shows progress on its button, disables it and guards against a double submit.
- [x] Tests: interceptor attach and skip rules, single-flight refresh, guards, login failure handling, session restore.

### 6.3 Branch: feat/folder-path-api (backend, OK-NOW)
- [x] Add an endpoint that returns the ancestor chain of a folder for breadcrumbs, scoped to the caller, returning 404 for other users.
- [x] Protect against cycles and cap the depth.
- [x] Tests: root folder, deep chain, stranger gets 404, soft-deleted ancestor handling.
- [x] Update the API list in docs.

### 6.4 Branch: feat/frontend-explorer (OK-NOW)
- [x] Explorer page for the root and for a folder id, with breadcrumbs from the new endpoint.
- [x] Folder list and file list with server pagination and a page size control.
- [x] Create folder dialog, rename, delete with confirmation, with the folder-not-empty and name-taken errors shown inline.
- [x] File rename and delete. - [ ] Moving a file to another folder is NOT built yet: it needs a folder picker (tree navigation); the API supports it (PATCH folder_id).
- [x] Download: request a signed link on click and navigate to it, never fetch it into memory, never store or log the link.
- [x] File status badge driven by the shared status union, with clear text for every status.
- [x] Loading skeletons, empty states and error states with retry on every list.
- [x] Keyboard operability through native controls and tab order, focus handling in dialogs via the native dialog element, screen reader labels on every row action. (No arrow-key list navigation; no real-browser check yet.)
- [x] File names are treated as untrusted text and always interpolated.
- [x] Tests: list states, create and rename error mapping, download link handling, pagination.

### 6.5 Branch: feat/frontend-upload (OK-NOW against the fake; BLOCKED-AWS for real)
- [ ] Upload queue store: per-file state (queued, requesting, uploading, completing, done, failed, cancelled), progress and speed.
- [ ] Choose files by button and by drag and drop. Client checks for size and type are advisory only.
- [ ] Flow: ask the API for upload instructions, send the form straight to storage with progress reporting and no auth header, then call complete.
- [ ] Cancel stops network work. A failed upload leaves the UI usable and shows the server message.
- [ ] Concurrency limit on parallel uploads.
- [ ] After complete, poll the file status with backoff until it reaches a final state, and stop polling when the page is left.
- [ ] Never read the whole file into memory.
- [ ] Tests: queue state machine, cancel, failure recovery, polling stop conditions, the Authorization header is absent on the storage call.
- [ ] Real upload test against the actual bucket once the owner provides AWS (BLOCKED-AWS), including verifying the bucket CORS settings.

### 6.6 Phase 3 exit criteria
- [ ] A new user can register, sign in, create folders, upload a file (against fake or real storage), see it, download it, rename, move and delete it.
- [ ] All frontend gates green. No console logging in shipped code. No inner HTML binding anywhere.
- [ ] Light and dark both checked on every screen. Phone width checked.

## 7. Phase 4 - Sharing and permissions

Goal: owners can share files and folders with other people at viewer or editor level, and every access check goes through one function.

### 7.1 Branch: docs/permissions-adr (DECISION first)
- [ ] Write docs/permissions.md: roles (owner, editor, viewer), what each can do per action, how folder grants inherit to children, what wins when grants conflict, what happens to a share when a file moves.
- [ ] Decide link sharing rules: expiry required or optional, view-only versus download, password optional or not.
- [ ] Decide how invitations to people without an account behave.
- [ ] Record as ADR.

### 7.2 Branch: feat/sharing-backend (OK-NOW)
- [ ] Migration: permissions table (resource type, resource id, grantee user, role, granted by, timestamps) with the right constraints and indexes, and a share links table (hashed token, expiry, role, revoked flag).
- [ ] Extend the single access function to evaluate grants and inheritance, deny by default, always returning 404 for unseen resources.
- [ ] Share endpoints: grant, change role, revoke, list who has access. Every action idempotent.
- [ ] Shared-with-me listing, paginated, filtered in the database.
- [ ] Share link create, revoke and resolve, token stored hashed only, expiry enforced, no listing of the underlying path.
- [ ] Editors can write but not re-share or delete unless the document allows it. Only owners manage sharing.
- [ ] Update every existing storage endpoint to pass through the extended access check (list, get, update, delete, download, upload into a shared folder).
- [ ] Tests: the full matrix of owner, editor, viewer, stranger and revoked for every action, inheritance cases, revoke takes effect immediately, link expiry, link revocation, no data leak through counts or error text.
- [ ] Query count tests for the shared listing.

### 7.3 Branch: feat/audit-logs (OK-NOW)
- [ ] Migration for the audit log table (actor, action, resource, result, request id, timestamp). No file contents and no file names in the log rows beyond ids.
- [ ] Audit service called from upload, download, share, revoke, delete and login events.
- [ ] Endpoint for an owner to read the audit trail of their own resources, paginated.
- [ ] Tests: event written exactly once per action, failure to write an audit row does not hide the original error, no sensitive data stored.

### 7.4 Branch: feat/frontend-sharing (OK-NOW)
- [ ] Share dialog: add person by email, choose role, list current access, change and revoke.
- [ ] Share link creation with expiry and copy button, revoke button.
- [ ] Shared-with-me page and role-aware UI (hide controls the role cannot use, while the server stays the authority).
- [ ] Activity view for a file from the audit endpoint.
- [ ] Tests: dialog validation, role-driven controls, revoke flow.

### 7.5 Optional branch inside Phase 4 if email is in scope: feat/email-flows (NEEDS-YOU: provider and key)
- [ ] Email verification on register, password reset with single-use expiring tokens stored hashed, share invitations.
- [ ] Email sending behind one small interface with a fake for tests.
- [ ] Tests for token expiry, reuse and enumeration safety.

### 7.6 Phase 4 exit criteria
- [ ] A second user can be given viewer or editor access and exactly those abilities work.
- [ ] Revoking removes access immediately. Strangers always see 404.

## 8. Phase 5 - Processing pipeline

Goal: after upload, files are scanned, text is extracted and chunked, and the file reaches a final status. Everything is idempotent and recoverable.

### 8.1 Branch: feat/multipart-upload (OK-NOW with fake S3; BLOCKED-AWS for real)
- [ ] Endpoints to start a multipart upload, get signed part addresses, and complete it, with size and part-count limits.
- [ ] Complete verifies the assembled object size and records the ETag.
- [ ] Abort endpoint and a lifecycle expectation for abandoned uploads.
- [ ] Raise the effective maximum size and document it.
- [ ] Frontend: part slicing, limited concurrency, per-part retry, ETag capture (needs the bucket to expose the header).
- [ ] Tests: happy path, missing part, wrong size, abort, stranger gets 404, repeated complete is safe.

### 8.2 Branch: feat/celery-pipeline (OK-NOW, needs only local Redis)
- [ ] Celery application and a worker entry point, beat schedule, task base settings: late acknowledgement, reject on worker loss, time limits, bounded retries with backoff and jitter for transient errors only.
- [ ] Processing jobs table: one row per stage per file version with status, attempt count, last user-safe error.
- [ ] Enqueue only after the database commit.
- [ ] Sweeper task that re-queues files stuck in uploaded, scanning or processing past a threshold.
- [ ] Broker visibility timeout set longer than the longest task.
- [ ] Request id carried into task logs.
- [ ] Tasks take ids only and re-read state; running twice gives the same result.
- [ ] Tests: task replay is a no-op, retry on transient error, no retry on permanent error, sweeper behaviour, enqueue-after-commit.
- [ ] Documentation of how to run the worker and beat locally.

### 8.3 Branch: feat/malware-scan (OK-NOW with a fake scanner; real scanning needs ClamAV installed)
- [ ] Scanner interface with two implementations: the real ClamAV one and a fake for tests.
- [ ] Stream the object from storage to the scanner in chunks, never whole into memory.
- [ ] Documented behaviour for files larger than the scanner stream limit (explicit fallback, never silent skip).
- [ ] Status transitions: uploaded to scanning to processing, or to infected (quarantine, never downloadable) or failed.
- [ ] Infected files cannot be downloaded or shared by anyone.
- [ ] Tests: clean, infected, scanner down (retry then failed), oversize file path.

### 8.4 Branch: feat/extraction-chunking (OK-NOW)
- [ ] Before scanning, compare the object's current ETag with the ETag stored at upload completion; a mismatch fails the file (the signed upload stays valid for its lifetime and could overwrite the object).
- [ ] Detect the real file type by content (magic bytes), not by name or the declared type; mismatch fails the file.
- [ ] Extractors for PDF, Word and Excel with hard limits: input size, page count, decompressed size, sheet and cell counts. Excel opened read-only.
- [ ] Empty extraction becomes needs_ocr, never ready.
- [ ] Remove NUL characters from all extracted text before storing.
- [ ] Deterministic chunking with chunk index, page or section, content hash and a stable size and overlap.
- [ ] Chunks table migration and the replace-in-one-transaction write so re-processing is idempotent.
- [ ] Final status ready only after chunks are stored.
- [ ] Tests: each format, zip bomb sample, corrupt file, empty file, NUL bytes, deterministic output, re-run gives identical chunks.

### 8.5 Branch: feat/purge-job (OK-NOW)
- [ ] Scheduled task that permanently removes soft-deleted files past a retention period: delete the S3 objects, then versions, chunks and rows.
- [ ] Also removes stale pending uploads and abandoned multiparts. Until it exists, abandoned pending_upload rows still count toward the storage quota (consider excluding pending rows older than the presign lifetime from the quota sum).
- [ ] Cleanup of expired refresh tokens and share links.
- [ ] Safe to run twice, bounded per run, logs counts only.
- [ ] Tests: retention boundary, partial failure leaves consistent state, repeat run is a no-op.

### 8.6 Phase 5 exit criteria
- [ ] A clean uploaded document reaches ready with chunks stored. An infected sample is quarantined. A scanned image-only PDF becomes needs_ocr. Killing a worker mid-task recovers via retry or the sweeper.

## 9. Phase 6 - Embeddings and semantic search

Goal: documents are searchable by meaning, and only by people allowed to see them.

### 9.1 Branch: docs/embedding-decision (DECISION, NEEDS-YOU)
- [ ] Choose the embedding model and record its name and vector size in an ADR.
- [ ] Define the single constants for model name and vector size.
- [ ] Decide similarity threshold defaults and top-k defaults.

### 9.2 Branch: feat/ai-gateway (OK-NOW against a fake; BLOCKED-APIM for real)
- [ ] One gateway module that is the only caller of the AI service. Settings supply base address, paths, deployment names and key. Nothing hard-coded.
- [ ] Shared pooled HTTP client with connect and read timeouts.
- [ ] Retry only on rate-limit, server error and timeout with bounded exponential backoff that honours the Retry-After header.
- [ ] Clean error mapping to an AI-unavailable error with no provider details or key leakage.
- [ ] Token usage recorded as counts only.
- [ ] Fake gateway for tests. Tests never call the real service.
- [ ] Run the APIM check script with the owner's values and record the real results (BLOCKED-APIM).

### 9.3 Branch: feat/embeddings (OK-NOW with fake; BLOCKED-APIM for real)
- [ ] Embedder interface with two implementations (gateway and local model) selected by settings.
- [ ] Migration: enable the vector extension, embeddings table with model name, dimension, chunk reference, vector column, and an approximate-nearest-neighbour index using cosine distance. Verify the test database role can create the extension.
- [ ] Embed task: batch chunks, assert the returned size equals the configured size, write idempotently, record the model name.
- [ ] Pipeline stage after chunking, file ready only after embeddings exist.
- [ ] Re-embed path for a model change (documented, not automatic).
- [ ] Tests: dimension mismatch rejected, batch boundaries, idempotent rewrite, fake embedder end-to-end.

### 9.4 Branch: feat/semantic-search (OK-NOW)
- [ ] Search endpoint: embed the query, filter by accessible files in the same database query, order by cosine distance, apply threshold, paginate.
- [ ] Handle the approximate-index under-fetch problem (over-fetch or iterative scan, version-checked).
- [ ] Return file id, chunk id, page and a short snippet only. No storage keys.
- [ ] Per-user rate limit hook for search.
- [ ] Tests: a user who can see only a small slice still gets correct results, shared-with-me results included, revoked results gone immediately, no cross-user leakage, threshold behaviour, empty result.

### 9.5 Branch: feat/frontend-search (OK-NOW)
- [ ] Search bar with debounce and request cancellation.
- [ ] Results list with file name, snippet, page, open file action.
- [ ] Search terms are kept in component state, never in the address bar or storage.
- [ ] States: searching, no results, AI unavailable with retry.
- [ ] Tests: debounce, cancellation, state transitions.

### 9.6 Phase 6 exit criteria
- [ ] Searching a paraphrase finds the right document in a real run (BLOCKED-APIM or local model), and tests prove permission filtering.

## 10. Phase 7 - AI features

Goal: ask questions about files, get cited answers, summaries, categories and comparisons, safely and within budgets.

### 10.1 Branch: feat/rag-chat (OK-NOW against fake; BLOCKED-APIM for real)
- [ ] Conversations and messages tables migration (no document text copied beyond what is needed, with model name, prompt version and token counts).
- [ ] Prompt module holding the system rules; retrieved chunks placed in a clearly delimited block labelled as untrusted document content.
- [ ] Retrieval reuses the permission-filtered search, with a similarity threshold and a token budget for context.
- [ ] No relevant context means a fixed honest answer, never a guess.
- [ ] Citations verified: only chunks actually retrieved may be cited, anything else dropped.
- [ ] Streaming endpoint with cancellation support.
- [ ] Per-user rate limit, monthly token budget, input and output size caps.
- [ ] No prompts, answers or chunk text in logs.
- [ ] No tools and no side effects for the model.
- [ ] Prompt injection test set: documents containing instructions, attempts to reveal the system prompt, attempts to cite foreign chunks, attempts to read other users' files.
- [ ] Tests with the fake gateway: citation filtering, no-context answer, budget exhausted, rate limit, stranger cannot read a conversation, cancellation.

### 10.2 Branch: feat/summaries-categories (OK-NOW against fake)
- [ ] Task generating a summary and a category with tags per file, stored with model and prompt version.
- [ ] Regenerate only when content changes. Cap the input size and handle very long documents by staged summarising.
- [ ] Endpoints to read them and to request a regeneration (rate-limited).
- [ ] Tests: idempotency, regeneration trigger, long document path, failure leaves the file usable.

### 10.3 Branch: feat/compare-docs (OK-NOW against fake)
- [ ] Endpoint that compares two documents the caller can access, with size caps and a structured result (similarities, differences) with citations.
- [ ] Tests: both documents access-checked, one inaccessible returns 404, caps enforced.

### 10.4 Branch: feat/frontend-ai (OK-NOW)
- [ ] Chat page with streamed answer rendering as plain text, stop button, retry, conversation list.
- [ ] Citation chips that open the cited file by id.
- [ ] Summary and category panel on a file.
- [ ] Compare view.
- [ ] Safe markdown rendering only through one shared sanitising component recorded by ADR, otherwise plain text.
- [ ] Tests: streaming states, cancel, citation links built only from server ids.

### 10.5 Phase 7 exit criteria
- [ ] Asking about a file returns a cited answer in a real run (BLOCKED-APIM). All injection tests pass. Budgets and limits enforced.

## 11. Phase 8 - Hardening, CI and deploy

### 11.1 Branch: feat/rate-limiting (OK-NOW, local Redis)
- [ ] Redis-based limits per IP and per account on the auth endpoints, and per user on AI and search endpoints.
- [ ] Clear 429 responses with Retry-After and the standard error shape.
- [ ] Add the CSRF header requirement on the refresh endpoint and update the frontend to send it.
- [ ] Tests: limits trigger, reset after the window, one user cannot exhaust another's budget.

### 11.2 Branch: feat/ci (OK-NOW)
- [ ] GitHub Actions workflows: backend (lint, format check, types, tests with a Postgres service that has the vector extension, and Redis), frontend (build, test, lint, format check).
- [ ] Cache dependencies. Require the workflows to pass before merge.
- [ ] Dependency vulnerability scan jobs for both tiers.
- [ ] Update the PR checklist docs. Enable branch protection (NEEDS-YOU in GitHub settings).

### 11.3 Branch: feat/containers (OK-NOW)
- [ ] Production container image for the API and for the worker, minimal, non-root, with health checks.
- [ ] Frontend static build served behind a reverse proxy that also proxies the API on the same origin.
- [ ] Compose file for a full local stack for people who do use Docker (optional).
- [ ] Document environment variables and the migration step on deploy.
- [ ] Verify images build (Docker must exist on the machine, NEEDS-YOU if not installed).

### 11.4 Branch: feat/observability (OK-NOW)
- [ ] Error tracking integration that scrubs bodies, headers and query strings.
- [ ] Tracing and metrics for request latency, task duration, queue depth and AI call counts.
- [ ] Security headers, strict CORS review, production settings review (docs disabled, secure cookies).
- [ ] Log review: confirm no document text, prompts, tokens or presigned links appear.

### 11.5 Branch: chore/security-and-load (OK-NOW)
- [ ] Dependency audit and updates, including resolving the test-client deprecation warning.
- [ ] Load test of list, upload initiation, search and chat endpoints with recorded results.
- [ ] Backup and restore procedure for the database tested once.
- [ ] Threat-model checklist walk-through against the CLAUDE.md security rules.

### 11.6 Branch: feat/deploy-azure (NEEDS-YOU: subscription and secrets)
- [ ] Container Apps for API, worker and beat; managed Postgres with pgvector enabled; managed Redis.
- [ ] Secrets in Key Vault, none in the repo or images.
- [ ] Static hosting for the frontend, same-origin routing to the API.
- [ ] Production migrations run as a controlled step.
- [ ] Smoke test checklist after deploy.

### 11.7 Branch: docs/final
- [ ] README with architecture overview, setup, run, test and deploy instructions.
- [ ] Architecture diagram, ER diagram, upload flow, auth flow and RAG flow, kept in docs.
- [ ] API reference list and an ADR index.
- [ ] Demo script or short recording notes.

### 11.8 Release
- [ ] Open the develop into main release PR (ask the owner first), review it, squash merge, tag the first release.

## 12. Backlog and known gaps

- [ ] The test client prints a deprecation notice about the HTTP library. Resolve during the dependency audit.
- [ ] AI quotas and token budgets per user are not built (the storage quota exists as a soft limit).
- [ ] Folder move (re-parenting) with cycle prevention is not built.
- [ ] File versions beyond version 1 (upload a new version, restore a version) are not built.
- [ ] Trash view and restore for soft-deleted items are not built.
- [ ] OCR for scanned documents is out of scope for the first release (files become needs_ocr).
- [ ] Google sign-in is out of scope unless the owner asks.
- [ ] Case-insensitive duplicate names for files are allowed on purpose, revisit if it confuses users.
- [ ] The register endpoint reveals whether an email exists (409). Accepted trade-off for now, revisit with email verification.
- [ ] Minor review findings that are not fixed in their PR must be listed here with the PR number.
- [ ] (PR 5, NEEDS-YOU) frontend/CLAUDE.md has two rules that conflict literally ("never auto-retry a write" and "retry once after a refresh on 401"). ADR 0006 records the chosen reading; owner to confirm or reword the standard (not edited by me).
- [x] (PR 5, backend) FIXED in PR 6: `display_name` was stripped after the min-length check, so a whitespace-only name can be stored as empty; fix in the backend with a stripped constrained string and add a test.
- [ ] (PR 5) No cross-tab logout sync (another tab stays signed in until its access token expires); no returnUrl after expiry; the access token is not refreshed proactively before it expires.
- [ ] (PR 5) If the logout API call fails the UI shows signed out but the refresh cookie may still be valid; cancelling a page mid-sign-in leaves state that heals on the next restore.
- [ ] (PR 6) Names made only of zero-width characters (U+200B, U+200C, U+200D, U+2060) are not stripped and display as invisible; reject names with no visible character for display names and file/folder names. A name truncated at 255 characters can end in a space (cosmetic).
- [ ] (PR 7, NEEDS-YOU) Root CLAUDE.md says 'no unpaged collection endpoint, ever'; ADR 0007 records the folder path exception. Owner to confirm or reword the standard (not edited by me).
- [ ] (PR 7) The permission matrix has only owner and stranger so far; editor, viewer and revoked arrive with sharing (Phase 4). Folder moves need cycle prevention before they exist.
- [ ] (PR 9) Explorer: file move needs a folder picker; no route titles or focus management on folder navigation; hostile-name rendering is covered by a test but no visual check in a real browser; the dialog does not close on backdrop click.
- [ ] (PR 4) Route titles and focus management on navigation are not built; add with the explorer (6.4).
- [ ] (PR 4) Folders have no index.ts public surfaces yet; add when the first cross-folder API grows.
- [ ] (PR 4) No automated accessibility checks and no real-browser light/dark/phone check yet.
- [ ] (PR 4) The busy button uses native disabled (per our standard), so keyboard focus is lost while busy; revisit with aria-disabled and a click guard if it hurts in the forms.
- [ ] (PR 4) Method calls in templates cannot be linted (signal reads are calls); the PR gate review enforces it. Revisit if angular-eslint adds a signal-aware rule.
- [ ] (PR 4) Production errors are dropped until telemetry exists (Phase 8 observability).
- [ ] (PR 1) The same workspace-scope lookup is duplicated in the folder and file services and costs two queries per request; extract once sharing lands in Phase 4.
- [ ] (PR 1) mypy covers the app package only, not tests; alembic migrations keep the generated boilerplate comments; the file_versions composite unique constraint name hides the version column.
- [ ] (PR 1) Repeat DELETE returns 404 on the second call (accepted); expired refresh tokens are purged by the Phase 5 purge job.
- [ ] (PR 1) Concurrency is covered by SQL lock assertions, not by a real two-session race test; the assertions cover upload init and folder delete but not create-folder or file move.
- [ ] (PR 2, NEEDS-YOU) backend/CLAUDE.md still says docs are disabled when the environment is production; the code now disables them unless development or test. Owner to approve the wording change (not edited by me).

## 13. Risks to watch

- The AI design depends entirely on what the owner's gateway really exposes. Verify early (BLOCKED-APIM).
- The embedding vector size cannot change without re-embedding everything. Decide before the first embedding migration.
- Approximate vector search combined with permission filters can return too few rows. Needs the dedicated test in Phase 6.
- Real S3 behaviour (CORS, multipart ETag exposure, presigned conditions) is only proven against a fake so far.
- The development laptop sleeping stops all unattended work. Keep it awake and plugged in.
- Commands that need approval stall unattended runs. Consider an allowlist of safe commands in settings.
