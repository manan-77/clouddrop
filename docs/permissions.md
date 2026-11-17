# Permissions and sharing

Decided with the owner: **a grant on a folder applies to everything inside it.** Everything else below follows from that and from the root `CLAUDE.md` (the server decides, a resource you may not see is a 404, deny by default).

## Roles and actions

| | viewer | editor | owner |
|---|---|---|---|
| read (list, open, see metadata, download) | yes | yes | yes |
| write (upload into a folder, create a subfolder, rename, move inside the shared tree) | no | yes | yes |
| delete | no | no | yes |
| share (grant, change, revoke, list who has access) | no | no | yes |

The **owner** is the owner of the workspace the resource lives in. It is implicit, never stored as a grant. Only `viewer` and `editor` are stored.

## Where a grant can be placed

On a **folder** or on a **file**, for one existing user. A folder grant covers all current and future descendants (folders and files). A file grant covers that file only.

## Which role applies

The effective role is the **highest** role among: a grant on the file itself and grants on every ancestor folder. There are no deny grants. Revoking a grant removes only that grant: access still given by another grant on an ancestor remains.

If any ancestor folder is deleted, non-owners lose access. Deleted items disappear for grantees immediately.

Evaluation is live on every request (no caching, no copying of grants to children), so a revoke or a move takes effect immediately.

## Moving

A file's own grants move with it. Inherited access is re-evaluated at the new location, so a file can gain or lose access by moving. A move needs `write` on the file and on the destination folder, stays inside one workspace, and only the owner may move something to the root.

## Rules for sharing

- Only the owner manages sharing. Other roles get 404, not 403, so they cannot tell what exists.
- A **file** can be shared only when its status is `ready` (the root contract: only ready files are shareable). Folders have no status gate. Because nothing becomes `ready` until the embeddings phase, tests and early use cover folders; file grants and grantee downloads switch on with `ready`.
- Non-owners can **see** only `ready` files (listing, opening, downloading); anything else (pending, scanning, failed, infected) is a 404 for them. The one exception is the uploader, who still sees their own unfinished uploads. Infected files are never downloadable by anyone.
- An upload in progress (parts, complete, abort) can be driven only by whoever started it or by the owner, so one editor cannot abort another's upload. The owner can always see and abort every pending upload in their workspace.
- The grantee is identified by **email and must already have an account**. An unknown email gives 404 `user_not_found`. This reveals whether an email has an account to a signed-in owner; the endpoint is rate limited and registration already behaves the same way, so this is accepted. Invitations to people without an account need an email provider and are out of scope.
- Granting to yourself is refused (422 `cannot_share_with_self`).
- Granting again to the same person updates the role (idempotent). Revoking a missing grant is 404.

## What a grantee sees

- **Shared with me** lists direct grants only (the top of each shared tree), paginated, filtered in the database.
- Breadcrumbs stop at the highest folder the grantee was given; ancestors above it are never revealed, and the `parent_id` of that top folder (and the `folder_id` of a file the grantee only has a file grant on) is returned as `null`.
- An editor cannot rename the top of the shared tree: its siblings belong to the owner's hidden tree and a name clash would reveal them (403 `shared_root_locked`).
- Content uploaded by an editor lives in the owner's workspace and counts against the **owner's** quota. Trade-off: an editor can reserve quota with pending uploads. Starting uploads is rate limited per user, and the owner can see and abort every pending upload; a per-uploader cap is not built.
- Search and AI (later phases) apply the same check inside the same SQL query.

## Link sharing (decided, built later)

Expiry is required (at most 30 days), links are view-only for a single resource, no password, and only a hash of the token is stored. Links are a public surface and get their own branch and review.

## Known and accepted information leaks to editors

An editor (never a viewer without write access) can infer two things about the owner's hidden tree: whether the owner's storage still has room (`quota_exceeded` against the owner's quota) and roughly how deep the shared folder sits (`folder_too_deep` counts hidden ancestors). The owner chose to grant write access, each probe costs a rate-limited upload or folder creation, and neither reveals names or content.

