# Security review against the CLAUDE.md baseline

Walk-through of the root and tier `CLAUDE.md` security rules, with where each is enforced and what is still open. "Evidence" names code or tests; "Open" is work that remains.

| Rule | Status | Evidence / open |
|---|---|---|
| Server decides, client reflects | Done | `AccessService` on every file/folder route; other users get 404 (tests in `test_files.py`, `test_folders.py`, `test_multipart.py`) |
| No secrets in git, bundle or logs | Done | `.env` git-ignored; CI uses throwaway values; logs reviewed below. Open: owner rotates the local DB password |
| Uploaded files and text are untrusted | Done | Server-derived keys, exact size/type presign conditions, HEAD verification, magic-byte type check, zip-bomb/page/size caps, never rendered as HTML. Open: real ClamAV run (needs install) |
| Scan before use | Done | Pipeline scans before type detection/extraction; infected is terminal and non-downloadable; scanner failure fails closed |
| S3 least privilege, no public access, CORS only the app, expose ETag | Owner | `docs/api.md` lists the IAM actions, the lifecycle rule, Block Public Access and the CORS origin rule. Exposing `ETag` is a deliberate deviation: the server lists multipart parts itself, so the browser never reads it (ADR 0009) |
| Rate-limit auth and AI endpoints | Partly | Login (per IP and per account), register and refresh are limited (`core/ratelimit.py`, tested); logout is not (low risk). The limiter fails open if Redis is down and depends on `FORWARDED_ALLOW_IPS` being set behind a proxy (the API only warns). Open: per-user limits when AI/search endpoints exist |
| PII never in logs, metrics, trackers, URLs, storage, analytics | Done with residual risk | See "Log review": two `logger.exception` sites (`processing/pipeline.py`, `core/errors.py`) log tracebacks with exception messages by design. No search terms or names in URLs; no tokens or names in browser storage (`localStorage` holds only the theme) |
| Same-origin, no baked host | Done | Relative `/api/v1`, dev proxy, nginx proxy in the web image |
| Auth: short access JWT in memory, rotating hashed refresh cookie, HttpOnly/Secure/SameSite=Strict | Done | `auth/service.py`, `auth/router.py`, tests for rotation, reuse detection, cookie flags; CSRF header on refresh/logout |
| Generic login errors | Done | `invalid_credentials` for unknown email, wrong password and inactive user. Known: `/auth/register` answers 409 for an existing email (enumeration; rate-limited, accepted for now) |
| Error shape, no stack/SQL/keys | Done | `core/errors.py`; unhandled errors return a generic body with a request id |
| Never return ORM, hash, token, S3 key, content hash | Done | Response schemas exclude them; the multipart upload id stays server-side (it appears only inside signed part URLs) |
| Docs/OpenAPI off outside local | Done | `Settings.docs_enabled`, tested |
| Secure cookies outside local | Done | `Settings.cookie_secure`, tested |
| Security headers | Done in the web image | nginx: CSP, nosniff, no-referrer, frame denial. Open: HSTS belongs to the TLS terminator |
| Dependencies | Done | `pip-audit` and `npm audit` clean on 2026-11-06; weekly `audit` workflow |
| Audit trail of access/permission changes | Open | Phase 4 (audit logs) |
| Sharing/permission inheritance | Open | Needs the owner's inheritance decision (Phase 4) |
| AI prompt-injection handling | Open | Phases 6-7 |
| Error tracking and metrics | Open | Needs the owner's choice of backend; the frontend reporter and backend logger are the plug-in points |

## Log review (2026-11-06)

Every `logger.*` call in `backend/app` was read. They log ids (file, version, job), counts, stage names, short machine error codes, and exception **class names**. None logs a request body, header, token, password, file name, document text, prompt, presigned URL, S3 key or upload id. SQLAlchemy bound parameters are hidden (`hide_parameters=True`) so a failed insert cannot print chunk text. The extractor catches parser exceptions and logs only the class name. Uvicorn access lines contain paths with ids and pagination query strings only. The frontend writes to the console only in development builds, through the single error reporter.

Residual risks: the two traceback sites above log exception messages, and a psycopg, pypdf or boto3 message could in theory contain data (hidden bound parameters cover only SQL values); the rate limiter fails open when Redis is down (a warning is logged, there is no metric yet).
