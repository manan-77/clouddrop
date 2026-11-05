# ADR 0007: The folder path endpoint is not paginated

Status: Accepted (owner to confirm the wording of the root standard)

## Context
The root `CLAUDE.md` says every list endpoint is paginated and there is no unpaged collection endpoint. `GET /api/v1/folders/{id}/path` returns the ancestor chain of one folder for breadcrumbs. It is a path, not a browsable collection, and paging a breadcrumb has no meaning.

## Decision
The endpoint returns the whole chain, root first. It is bounded by a nesting limit of 50 levels that is enforced when a folder is created (`folder_too_deep`), so the response is small and can never be silently truncated. The query also stops at the limit as a second safeguard.

## Consequences
- The standard has one documented exception; the owner should confirm or reword the rule. The author did not edit the standards file.
- Introducing folder moves later must keep the limit and add cycle prevention, because the recursive query relies on an acyclic chain.
