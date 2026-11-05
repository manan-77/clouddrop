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

## Folders (`/api/v1/folders`) - authenticated
| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `` | 200 page | `parent_id` omitted = root |
| POST | `` | 201 + `Location` | Body `name`, optional `parent_id`. 409 `folder_name_taken` |
| GET | `/{folder_id}` | 200 | |
| PATCH | `/{folder_id}` | 200 | Rename. 409 on a sibling name clash |
| GET | `/{folder_id}/path` | 200 list | The folder and its ancestors, root first, for breadcrumbs. Not paginated on purpose: bounded by a depth cap of 50. 404 for other users' folders |
| DELETE | `/{folder_id}` | 204 | Soft delete. 409 `folder_not_empty` |

## Files (`/api/v1/files`) - authenticated
| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `` | 200 page | Filters `folder_id` (omitted = root) and `status` |
| POST | `/uploads` | 201 + `Location` | Body `name`, `content_type`, `size_bytes`, optional `folder_id`. Returns the file and a presigned POST (`url`, `fields`, `expires_in`). 422 `file_too_large`, `unsupported_file_type`, `quota_exceeded` |
| POST | `/{file_id}/uploads/complete` | 200 | Verifies the stored object size. Safe to repeat: a repeat on a file that is no longer pending returns it unchanged (a failed file returns 200 with status `failed`). 409 `upload_incomplete`, 422 `upload_size_mismatch` |
| GET | `/{file_id}` | 200 | |
| PATCH | `/{file_id}` | 200 | `name` and/or `folder_id` (explicit null moves to root). 422 `empty_update` |
| DELETE | `/{file_id}` | 204 | Soft delete; the stored object is purged later |
| GET | `/{file_id}/download` | 200 `{url, expires_in}` | Short-lived link forced to download. 409 `file_not_ready`, 403 `file_infected` |

While no bucket is configured (`S3_BUCKET` empty), **every** `/api/v1/files*` route returns 503 `storage_not_configured`, because the S3 dependency is resolved for all of them. Auth, folders and health are unaffected.
