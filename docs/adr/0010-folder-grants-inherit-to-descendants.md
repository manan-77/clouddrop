# 0010 - Folder grants inherit to descendants; access is evaluated live

## Context

Phase 4 adds sharing. Until now the only check was "is this your workspace". The owner decided that a grant on a folder applies to everything inside it.

## Decision

- Grants (`viewer`, `editor`) are stored per folder or per file in one `permissions` table with two nullable foreign keys (exactly one set), so referential integrity is real and rows cascade when the resource is purged.
- The effective role is the highest of the file's own grants and the grants on all its ancestor folders, computed with a recursive query on every request. Nothing is cached or copied, so revoking or moving takes effect immediately. There are no deny grants.
- `AccessService` remains the single function every storage path goes through; the `sharing` module reads the `folders` and `files` tables directly, as the `processing` module does (ADR 0008), to avoid a circular service dependency.
- Resource lookups no longer filter by the caller's workspace; they find the resource and ask `AccessService`. Anything the caller may not read is a 404.

## Deviation from backend/CLAUDE.md (logged for the owner)

The backend standard says repositories have no unscoped "get by id" and modules reach each other only through services. Sharing cannot work with workspace-scoped lookups (the grantee is not in the owner's workspace), so `get_any` finds an active folder or file by id and the service must call `AccessService` before returning it; every service path does, and tests cover the denial for each action. The `sharing` module also reads the `folders` and `files` tables directly (see ADR 0008).

## Consequences

- One recursive query per access check (folders are capped at 50 levels). Listing under a shared folder checks the folder once, not per child.
- Content created by editors belongs to the owner's workspace and quota.
- Deleting a shared folder is owner-only and still requires it to be empty.
- Link sharing and invitations are separate decisions (see `docs/permissions.md`).
