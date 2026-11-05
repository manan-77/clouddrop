# ADR 0006: The single retry after a 401 includes writes

Status: Accepted (owner to confirm the wording of the frontend standard)

## Context
`frontend/CLAUDE.md` says never to auto-retry a write, and also says a 401 triggers one shared refresh and a retry of the original request. Read literally these conflict for POST, PATCH and DELETE.

## Decision
The interceptor retries the original request once after a successful refresh, for every HTTP method. A 401 is produced by the authentication layer before any handler runs, so the first attempt had no side effect; repeating it cannot duplicate a write. A request that is retried is marked and is never retried again. Requests that failed for any other reason are never retried automatically.

## Consequences
- The first action after the access token expires does not fail for the user.
- If a future API returns 401 after performing work, this decision must be revisited.
- The standards file should state the exception explicitly. It was not edited by the author of this change; it is tracked in `tasks/todo.md` for the owner.
