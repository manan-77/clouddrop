# Architecture decision records

One file per decision: context, decision, consequences. Add a new file for every architectural decision; never rewrite history, supersede instead.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-sync-sqlalchemy-and-def-endpoints.md) | Synchronous SQLAlchemy and plain `def` endpoints | Accepted |
| [0002](0002-uv-and-python-3-12.md) | uv for dependencies, Python 3.12 pinned | Accepted |
| [0003](0003-local-postgres-with-pgvector.md) | Local Postgres 17 with pgvector instead of Docker for development | Accepted |
| [0004](0004-angular-21-pinned.md) | Angular 21 pinned because local Node 25 does not satisfy Angular 22 | Accepted |
| [0005](0005-design-tokens-no-ui-kit.md) | Plain SCSS design tokens, no UI kit | Accepted |
