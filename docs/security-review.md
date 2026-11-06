# Security review against the CLAUDE.md baseline

Walk-through of the root and tier `CLAUDE.md` security rules, with where each is enforced and what is still open. "Evidence" names code or tests; "Open" is work that remains.

| Rule | Status | Evidence / open |
|---|---|---|
| Server decides, client reflects | Done | `AccessService` on every file/folder route; other users get 404 (tests in `test_files.py`, `test_folders.py`, `test_multipart.py`) |
| No secrets in git, bundle or logs | Done | `.env` git-ignored; CI uses throwaway values; logs reviewed below. Open: owner rotates the local DB password |
| Uploaded files and text are untrusted | Done | Server-derived keys, exact size/type presign conditions, HEAD verification, magic-byte type check, zip-bomb/page/size caps, never rendered as HTML. Open: real ClamAV run (needs install) |
| Scan before use | Done | Pipeline scans before type detection/extraction; infected is terminal and non-downloadable; scanner failure fails closed |
| S3 least privilege, no public access, CORS only the app, expose ETag | Owner | Written in `docs/api.md` (IAM actions, lifecycle rule, CORS for PUT). The server lists multipart parts itself, so `ExposeHeaders: ETag` is not needed |
| Rate-limit auth and AI endpoints | Partly | Auth endpoints limited (`core/ratelimit.py`, tested). Open: per-user limits when AI/search endpoints exist |
| PII never in logs, metrics, trackers, URLs, storage, analytics | Done (reviewed) | See "Log review". No search terms or names in URLs; no browser storage of tokens or names |
| Same-origin, no baked host | Done | Relative `/api/v1`, dev proxy, nginx proxy in the web image |
| Auth: short access JWT in memory, rotating hashed refresh cookie, HttpOnly/Secure/SameSite=Strict | Done | `auth/service.py`, `auth/router.py`, tests for rotation, reuse detection, cookie flags; CSRF header on refresh/logout |
| Generic login errors | Done | `invalid_credentials` for unknown email and wrong password |
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

Residual risks: an unexpected third-party exception message could in theory contain data (the pipeline logs a traceback for unexpected errors by design); the rate limiter fails open when Redis is down (a warning is logged, there is no metric yet).
