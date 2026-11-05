# ADR 0001: Synchronous SQLAlchemy and plain `def` endpoints

Status: Accepted

## Context
The API and the Celery workers share one codebase. Celery tasks are synchronous. boto3, pypdf and python-docx are blocking libraries. Mixing async database code with blocking calls inside `async def` endpoints blocks the event loop and is a common source of subtle bugs.

## Decision
Use SQLAlchemy 2.0 with the synchronous engine and psycopg 3. Endpoints are plain `def`, which FastAPI runs in a thread pool. Services and repositories are synchronous and shared unchanged by the API and the workers. Async is used only where it is genuinely needed (for example streaming an AI response), and such endpoints must not touch the database or blocking libraries inside the stream.

## Consequences
- One session style everywhere; repositories are reusable from tasks.
- Concurrency is bounded by the thread pool and the database pool size, which are configuration.
- If throughput later demands async I/O, the change is contained: replace the session factory and repositories, not the services' rules.
