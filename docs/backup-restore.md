# Database backup and restore

Postgres is the only store of record for users, metadata and processing state; files live in S3 (use bucket versioning there). Redis holds nothing that cannot be rebuilt (the sweeper re-enqueues from Postgres).

## Backup

Use the `pg_dump` that matches the **server** major version (the Homebrew `postgresql@17` binaries here; the default `pg_dump` on this Mac is 14 and refuses to dump a 17 server):

```bash
export PGPASSWORD=...        # from your secret store, never on the command line
/opt/homebrew/opt/postgresql@17/bin/pg_dump -Fc -h localhost -U clouddrop -d clouddrop -f clouddrop.dump
```

The custom format is compressed and restorable selectively. Keep dumps encrypted and off the repository: they contain user email addresses and file names (treated like PHI in this project).

## Restore

Restore into an empty database, never over the live one:

```bash
createdb -h localhost -U <role with CREATEDB> clouddrop_restore
/opt/homebrew/opt/postgresql@17/bin/pg_restore -d clouddrop_restore --no-owner clouddrop.dump
psql -d clouddrop_restore -c "select version_num from alembic_version"   # must match the code's head
```

Then compare row counts per table with the source, point a staging API at the restored database and run `GET /health/ready`. For a managed Postgres, prefer the provider's point-in-time recovery and rehearse it the same way.

## What was verified (2026-11-06)

- A read-only dump of the local development database with the PG17 client succeeded, and `pg_restore --list` read the archive (47 entries, data for all 8 tables in that database).
- **Not verified:** the restore itself. The application's database role has no `CREATEDB` permission, so a scratch database could not be created without using a more privileged role. Run the restore steps above once with an admin role before relying on this procedure (owner action).
- The local development database is behind the code's migrations (it lacks `document_chunks` and later); run `alembic upgrade head` before a meaningful restore check.
