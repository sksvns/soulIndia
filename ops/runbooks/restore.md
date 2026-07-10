# Backup & restore runbook

## How nightly backups work

`manage.py backup_database` (`backend/apps/ingestion/management/commands/backup_database.py`):

1. Runs `pg_dump -Fc` (Postgres's custom format -- compressed, and the
   only format `pg_restore` can parallelize or selectively restore from)
   against the live database.
2. Uploads the dump to the configured object storage (same
   `OBJECT_STORAGE_*` config as file uploads -- MinIO in dev, an
   S3-compatible provider in prod, see `backend/apps/ingestion/storage.py`)
   under a `backups/` prefix, named `backups/<db_name>_<UTC timestamp>.dump`.
3. Deletes older backups beyond `--retention` (default: the
   `BACKUP_RETENTION_DAYS` env var, or 14).

### Scheduling

Not run by any container automatically -- schedule it from the *host* via
cron, once per night:

```cron
0 2 * * * cd /path/to/soulIndia && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend python manage.py backup_database >> /var/log/soulindia-backup.log 2>&1
```

### Running it manually

```bash
docker compose exec backend python manage.py backup_database
```

## Restore drill -- results (verified 2026-07-10)

Ran for real against this project's actual dataset at Day-11 load-test
scale (36,792,391 `fact_sales` rows across 3 synthetic + 3 real brands,
36.8M rows total, ~1.07 GB compressed dump) -- not a toy dataset, so these
numbers reflect a realistic restore time.

1. `manage.py backup_database` produced `backups/retail_analytics_
   20260710T191458.dump` (1073.06 MB).
2. Downloaded it from object storage and restored into a **separate
   scratch database** (`retail_analytics_restore_test`) on the same
   Postgres instance -- never touched the live database.
3. `pg_restore --no-owner --jobs=4` completed in **181 seconds** (~3
   minutes) -- comfortably inside the ~30 minute target.
4. Verified data integrity by comparing row counts against the live
   database: `fact_sales` (36,792,391 == 36,792,391), `mv_category_perf`
   (4,828,316 == 4,828,316), and `django_migrations` (39 rows, confirming
   Django's own schema-version bookkeeping round-trips correctly too).
5. Dropped the scratch database.

**Known benign warning:** `pg_restore` reported `unrecognized
configuration parameter "transaction_timeout"` on 2 of the 4 parallel
worker connections (`errors ignored on restore: 2`). This is a
Postgres-17-vs-16 client/server mismatch -- our backend image's
`postgresql-client` is v17 (Debian trixie's default), the database server
is `postgres:16`, and `transaction_timeout` is a v17-only session
parameter `pg_restore` tries to set on connect. It affects only session
setup, not schema or data, and is exactly why step 4 above independently
verifies row counts rather than trusting `pg_restore`'s own exit status.
If this ever needs to go away instead of just being tolerated, pin the
image to `postgresql-client-16` via the PGDG apt repository.

## How to actually restore in an incident

**This is a manual, deliberate procedure -- not a single automated
command.** A restore is rare and high-stakes (it can overwrite the live
database), so it stays a checklist a human runs deliberately rather than
a script that could fire at the wrong target by accident.

1. Identify the backup to restore from:
   ```bash
   docker compose exec backend python manage.py shell -c "
   from apps.ingestion import storage
   print(sorted(storage.list_keys('backups/')))
   "
   ```
2. Download it into the backend container:
   ```bash
   docker compose exec backend python manage.py shell -c "
   from apps.ingestion import storage
   body = storage.get('backups/<the-key-you-picked>.dump')
   with open('/tmp/restore.dump', 'wb') as f:
       f.write(body.read())
   "
   ```
3. **Stop the app from writing during the restore** (backend + celery),
   so nothing races the restore:
   ```bash
   docker compose stop backend celery
   ```
4. Restore. For a genuine incident (restoring *over* the live database,
   not into a scratch one), drop and recreate it first so `pg_restore`
   starts from a clean slate rather than merging with whatever's left:
   ```bash
   docker compose exec backend sh -c "
     PGPASSWORD=\$POSTGRES_PASSWORD psql -h db -U \$POSTGRES_USER -d postgres \
       -c 'DROP DATABASE retail_analytics;' \
       -c 'CREATE DATABASE retail_analytics;'
     PGPASSWORD=\$POSTGRES_PASSWORD pg_restore -h db -U \$POSTGRES_USER \
       -d retail_analytics --no-owner --jobs=4 /tmp/restore.dump
   "
   ```
5. Spot-check row counts against what you expect (see step 4 of the drill
   above) before resuming traffic.
6. Restart the app:
   ```bash
   docker compose start backend celery
   ```

## Seeding the initial Super Admin (fresh deployment)

A brand-new production database has no users at all, so nobody can use
Django admin's own "add user" screen yet. Bootstrap the first one with:

```bash
docker compose exec backend python manage.py create_super_admin \
  --email=you@yourcompany.com --password='<a real generated password>'
```

This also runs `seed_roles` internally (creating the "Super Admin" /
"Data Inserter" groups if they don't exist yet), so it's safe to run as
the very first command against a fresh database. Idempotent -- re-running
with the same email just updates that user's password and group
membership rather than erroring, so it also works as a "reset the admin
password" escape hatch later.
