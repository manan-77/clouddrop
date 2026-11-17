# 0011 - Audit events commit with the action and hold ids only

## Context

Phase 4 needs a trail of uploads, downloads, deletes, sharing changes and logins that an owner can read.

## Decision

- One append-only `audit_events` table. Each row names the **workspace** whose owner may read it, so an owner sees everything that happens to their resources, including what editors do. The resource id has no foreign key, so the trail outlives a purged file.
- An event for a successful action is added to the **same transaction** as the action. If the audit row cannot be written, the action does not happen (fail closed). Events for outcomes with nothing else to commit (a failed login) are written on their own and never raise, so they cannot hide the original error.
- Rows hold ids and short machine codes only: no file names, emails, tokens, URLs or content. Action, result and resource type are CHECK-constrained text.
- `created_at` uses `clock_timestamp()`, so rows from one transaction still order by when they happened.
- Failed logins are recorded only for existing accounts, in that account's own trail; an unknown email leaves no row.

## Consequences

- No retention or purge of audit rows yet (a later decision).
- Read access is workspace-scoped; per-resource sharing of the trail (letting editors see activity) is not supported.
