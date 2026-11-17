# API reference (current)

Auth, folder and file routes live under `/api/v1`. The health routes are NOT under that prefix: they are `/health` and `/health/ready`. Authenticated routes need `Authorization: Bearer <access token>`. Lists are paginated with `page` (1 to 100000, default 1) and `page_size` (1 to 100, default 50) and return `{items, total, page, page_size}`. Every failure uses one envelope:

`{"error": {"code": "...", "message": "...", "request_id": "...", "details": []}}`

Resources that do not belong to the caller return 404, never 403. The interactive documentation is served at `/docs` only in the development and test environments.

## Health
| Method | Path | Auth | Success |
|---|---|---|---|
| GET | `/health` | no | 200 `{status}` |
| GET | `/health/ready` | no | 200, or 503 `db_unavailable` |

## Auth (`/api/v1/auth`)
| Method | Path | Success | Notes |
|---|---|---|---|
| POST | `/register` | 201 + `Location` | Creates the user and a personal workspace. 409 if the email exists, 422 on validation |
| POST | `/login` | 200 token | Sets the refresh cookie (HttpOnly, SameSite=Strict, path `/api/v1/auth`, Secure outside local environments). 401 `invalid_credentials` (same message for an unknown email and a wrong password) |
| POST | `/refresh` | 200 token | Reads the cookie, rotates it. Reusing an old token revokes the whole family. 401 `invalid_session` for a missing, unknown, expired or revoked cookie |
| POST | `/logout` | 204 | Revokes the token family and clears the cookie |
| GET | `/me` | 200 user | Authenticated |

Rate limits (fixed window, Redis, per IP and for login also per account; defaults in `Settings`): login 20 per IP and 10 per account per 15 minutes, register 10 per IP per hour, refresh 60 per IP per minute. Grants are limited to 60 per hour per user (`RATE_LIMIT_GRANT_PER_USER`, window `RATE_LIMIT_GRANT_WINDOW_SECONDS`), and an editor starting uploads into someone else's shared folder to 120 per hour per user (`RATE_LIMIT_UPLOAD_INIT_PER_USER`, `RATE_LIMIT_UPLOAD_INIT_WINDOW_SECONDS`); owners uploading into their own space are not limited. Exceeding one returns **429** `rate_limited` with a `Retry-After` header. The per-account login budget is per (account, client), so a stranger cannot lock the owner out; guessing spread over many clients is bounded by the per-IP limit and the password hashing cost. IPv6 clients share one budget per /64. If Redis is down the limiter fails open and logs a warning.

**Deployment:** the client address is the socket peer. Behind the reverse proxy the API must run with `--proxy-headers --forwarded-allow-ips=<proxy address>` (tracked in the containers task), otherwise every user shares one budget.

`/refresh` and `/logout` also require the header `X-Requested-With: XMLHttpRequest`; without it they return **403** `csrf_check_failed`. The frontend sends it on both calls.

## Folders (`/api/v1/folders`) - authenticated
| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `` | 200 page | `parent_id` omitted = root |
| POST | `` | 201 + `Location` | Body `name`, optional `parent_id`. 409 `folder_name_taken`, 422 `folder_too_deep` (more than 50 levels) |
| GET | `/{folder_id}` | 200 | |
| PATCH | `/{folder_id}` | 200 | Rename. 409 on a sibling name clash |
| GET | `/{folder_id}/path` | 200 list | The folder and its ancestors, root first, for breadcrumbs. Not paginated on purpose: bounded by a depth cap of 50. 404 for other users' folders |
| DELETE | `/{folder_id}` | 204 | Soft delete. 409 `folder_not_empty` |

## Files (`/api/v1/files`) - authenticated
| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `` | 200 page | Filters `folder_id` (omitted = root) and `status` |
| POST | `/uploads` | 201 + `Location` | Body `name`, `content_type`, `size_bytes`, optional `folder_id`. Returns the file and a presigned POST (`url`, `fields`, `expires_in`). 422 `file_too_large`, `unsupported_file_type`, `quota_exceeded` |
| POST | `/uploads/multipart` | 201 + `Location` | Same body as `/uploads`; size up to `MULTIPART_MAX_UPLOAD_BYTES` (1 GiB). Returns the file and `multipart` (`part_size_bytes`, `part_count`, `expires_in`); the server chooses the part layout and keeps the S3 upload id in the database (the signed part URLs necessarily contain it, scoped to one part and a short lifetime). Same 422 codes as `/uploads` |
| POST | `/{file_id}/uploads/parts` | 200 | Body `part_numbers` (1-100 numbers). Returns a presigned PUT URL per part with the exact part size signed in. 409 `not_multipart_upload`, 422 `invalid_part_number`. Presign again to retry a part |
| DELETE | `/{file_id}/uploads` | 204 | Aborts a pending upload (multipart or single), deletes what was uploaded and removes the file. 409 `upload_not_pending` |
| POST | `/{file_id}/uploads/complete` | 200 | Verifies the stored object size. For a multipart upload the server lists the uploaded parts itself (the client sends no part list or ETags), checks every part against the layout it chose, assembles them, then verifies the final size; a missing part is 409 `upload_incomplete` and wrong part sizes fail the file with 422 `upload_size_mismatch`. Safe to repeat: a repeat on a file that is no longer pending returns it unchanged (a failed file returns 200 with status `failed`). 409 `upload_incomplete`, 422 `upload_size_mismatch` |
| GET | `/{file_id}` | 200 | |
| PATCH | `/{file_id}` | 200 | `name` and/or `folder_id` (explicit null moves to root). 422 `empty_update` |
| DELETE | `/{file_id}` | 204 | Soft delete; the stored object is purged later |
| GET | `/{file_id}/download` | 200 `{url, expires_in}` | Short-lived link forced to download. 409 `file_not_ready`, 403 `file_infected` |

While no bucket is configured (`S3_BUCKET` empty), only the routes that talk to S3 return 503 `storage_not_configured`: upload init, upload completion and download. Listing, reading, renaming and deleting files, folders, auth and health are unaffected.

## Sharing (`/api/v1`) - authenticated

Rules are in `docs/permissions.md`: a grant on a folder covers everything inside it; viewer reads, editor reads and writes, only the owner deletes and shares. A caller without access gets 404.

| Method | Path | Success | Notes |
|---|---|---|---|
| POST | `/folders/{id}/permissions`, `/files/{id}/permissions` | 201 + `Location`, or 200 when the grant already existed (role updated) | Body `email` (an existing account), `role` (`viewer` or `editor`). 404 `user_not_found`, 422 `cannot_share_with_self`, 409 `file_not_ready` (files must be `ready`), 429 after 60 grants per hour |
| GET | `/folders/{id}/permissions`, `/files/{id}/permissions` | 200 paginated | Owner only |
| GET / PATCH / DELETE | `.../permissions/{permission_id}` | 200 / 200 / 204 | PATCH body `role`. Revoking takes effect immediately |
| GET | `/shared-with-me` | 200 paginated | Direct grants only (`resource_type`, `id`, `name`, `role`, `owner_name`, and for files `size_bytes`, `content_type`, `status`) |

Existing folder and file endpoints now accept resources in a shared tree according to the caller's role. Breadcrumbs for a grantee start at the folder they were given and the hidden parent id is `null`. Non-owners see and download only `ready` files (plus their own unfinished uploads). Upload init endpoints are rate limited per user (429).

## Audit trail (`/api/v1/audit-events`) - authenticated

| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `/audit-events` | 200 paginated, newest first | Activity in the caller's own workspace (including what editors did there). Filters `resource_type` (`file`, `folder`, `user`) and `resource_id`. Items: `action`, `resource_type`, `resource_id`, `actor_id`, `actor_name`, `target_user_id`, `detail` (the role for grants), `request_id`, `created_at`. Someone else's resource id gives an empty page |

Recorded actions: `file.uploaded` (when complete succeeds), `file.downloaded` (when a link is issued), `file.deleted`, `folder.deleted`, `permission.granted`, `permission.changed`, `permission.revoked`, and `auth.login` (successful sign-ins). **Not recorded:** failed logins, denied attempts and failed uploads (an unauthenticated caller must not be able to write into someone's trail, and extra work for known emails would be a timing oracle). Issuing a download link writes a row, so a repeated request is a repeated event; a grantee's link requests are limited to 600 per hour per user (`RATE_LIMIT_DOWNLOAD_PER_USER`); owners downloading their own files are not limited. Actions by editors are written to the owner's trail. Rows hold ids and short codes only, never names, emails, tokens or URLs; the request id is the one the request carried (letters, digits, `_` and `-`, at most 64).

## Storage setup notes (S3)

- The IAM identity needs `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:AbortMultipartUpload` and `s3:ListMultipartUploadParts` on the bucket prefixes.
- **Required:** a lifecycle rule `AbortIncompleteMultipartUpload` after 7 days. The purge job aborts abandoned uploads (after `MULTIPART_UPLOAD_MAX_AGE_SECONDS`, 6 hours), but a part still in flight during an abort, or a crash between creating the upload and saving the row, can leave parts that only this rule cleans up.
- Block all public access on the bucket. Browser CORS must list only the app origin and allow `POST` (single uploads) and `PUT` (parts); `ETag` need not be exposed (ADR 0009).
- The effective maximum is `MAX_UPLOAD_BYTES` (single request, 100 MiB) or `MULTIPART_MAX_UPLOAD_BYTES` (1 GiB, multipart). The settings refuse a multipart maximum above `SCANNER_MAX_STREAM_BYTES` while scanning is on, so a file is never accepted and then failed for being too large to scan.
