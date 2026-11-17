# 0011 - Audit events commit with the action and hold ids only

## Context

Phase 4 needs a trail of uploads, downloads, deletes, sharing changes and logins that an owner can read.

## Decision

- One `audit_events` table. Each row names the **workspace** whose owner may read it, so an owner sees everything that happens to their resources, including what editors do. The resource id has no foreign key, so the trail outlives a purged file.
- An event for a successful, authorised action is added to the **same transaction** as the action. If the audit row cannot be written, the action does not happen (fail closed).
- Only authenticated, authorised outcomes are recorded. **Failed logins, denied attempts and failed uploads are not**: an unauthenticated caller could flood a victim's trail, and the extra work for a known email would be a timing oracle for account existence. Rate limits and logs cover those.
- A role change is recorded only when the role actually changes.
- Rows hold ids and short machine codes only: no file names, emails, tokens, URLs or content. Action and resource type are CHECK-constrained text (there is no result column: every row is a success); a test inserts every enum member so the migration literals cannot drift from the enums.
- `created_at` uses `clock_timestamp()`, so rows from one transaction still order by when they happened.
- The module follows router -> service -> repository. `audit` joins the `users` table directly for the actor's display name (an exception to the module-boundary rule, like ADR 0008).

## Consequences

- Issuing a download link now writes and commits in a GET, and a repeated request is a repeated event; a client that never uses the link still logs a download. Link requests are rate limited per user so a grantee cannot grow the owner's trail without bound.
- The table is append-only by convention (no code path updates or deletes a row). The database cannot enforce it because the foreign-key actions (`SET NULL`, `CASCADE`) need UPDATE and DELETE.
- There is no retention or purge of audit rows yet, and the total count runs per page request; both are a later decision if the table grows.
- The request id is stored as the request carried it (the middleware limits it to letters, digits, `_` and `-`, at most 64), so an authenticated user can choose the text of their own events' request ids.
- Read access is workspace-scoped; letting editors see activity is not supported.
