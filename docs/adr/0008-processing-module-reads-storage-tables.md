# ADR 0008: The processing module reads the storage tables directly

Status: Accepted (owner to confirm the wording of the backend standard)

## Context
The backend standard says a module reaches another module only through that module's service. The processing worker has no user and no workspace, so the services in `storage` (which are scoped to the caller's workspace) cannot serve it. It needs rows by version id, to find stuck files, and to move a file along the status machine.

## Decision
`app/modules/processing` has its own repository that reads `files` and `file_versions` directly and only changes a file's status. Everything a user can see or change still goes through the `storage` services. Enqueueing goes the other way: `storage` calls the processing dispatcher, which sends a task carrying only a version id.

## Consequences
- The worker side of the file tables is one small repository, easy to audit.
- If the file tables change shape, `processing/repository.py` must change with them.
- The stages also import the storage S3 wrapper and the file status constants; they are the same worker-side coupling and are covered by this decision.
- The standard has an explicit exception for worker-side modules; the owner should confirm or reword it. The author did not edit the standards file.
