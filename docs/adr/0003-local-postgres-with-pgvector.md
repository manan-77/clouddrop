# ADR 0003: Local Postgres 17 with pgvector instead of Docker for development

Status: Accepted

## Context
The development machine has no Docker. The project needs PostgreSQL with the pgvector extension and Redis.

## Decision
Run PostgreSQL 17 (Homebrew) with pgvector 0.8.x and Redis directly on the machine. The database is `clouddrop` and the tests use a separate `clouddrop_test` database that is rebuilt from the migrations at the start of each test session. `docker-compose.yml` stays in the repository as an optional alternative.

## Consequences
- Postgres 17 listens on the default port 5432; older local clusters must not use the same port.
- Test runs only ever touch `clouddrop_test`; the development database is never downgraded by tests.
- Anyone without these services installed can use the compose file instead. Note the compose file currently uses the `pgvector/pgvector:pg16` image, a different major version from the local Postgres 17; bump it before relying on it.
- The vector extension is created by a superuser; a migration that needs it must account for the role that runs the migrations.
