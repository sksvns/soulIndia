"""Day 12: nightly database backup. Runs pg_dump in Postgres's custom
format (-Fc: compressed, and the only format pg_restore can selectively
restore from or parallelize), uploads it to the configured object storage
(same OBJECT_STORAGE_* config/client as file uploads -- MinIO in dev,
S3-compatible in prod, see apps.ingestion.storage) under a backups/
prefix, then deletes older backups beyond the retention count.

Intended to run nightly via host cron:
    docker compose exec -T backend python manage.py backup_database
See ops/runbooks/restore.md for the restore drill this was verified against.
"""

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.ingestion import storage

BACKUP_PREFIX = "backups/"


class Command(BaseCommand):
    help = "pg_dump the database and upload it to object storage, pruning old backups."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention",
            type=int,
            default=None,
            help="Backups to keep (default: BACKUP_RETENTION_DAYS env var, or 14).",
        )

    def handle(self, *args, **options):
        retention = options["retention"] or int(os.environ.get("BACKUP_RETENTION_DAYS", "14"))

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        db_name = connection.settings_dict["NAME"]
        key = f"{BACKUP_PREFIX}{db_name}_{timestamp}.dump"

        with tempfile.TemporaryDirectory() as tmpdir:
            dump_path = Path(tmpdir) / "backup.dump"
            self._run_pg_dump(dump_path)
            size_mb = dump_path.stat().st_size / (1024 * 1024)
            with open(dump_path, "rb") as fh:
                storage.put(key, fh, content_type="application/octet-stream")
        self.stdout.write(self.style.SUCCESS(f"Uploaded {key} ({size_mb:.2f} MB)"))

        self._prune_old_backups(retention)

    def _run_pg_dump(self, dump_path: Path) -> None:
        db = connection.settings_dict
        env = {"PGPASSWORD": db["PASSWORD"]}
        result = subprocess.run(
            [
                "pg_dump",
                "-Fc",
                "-h",
                db["HOST"],
                "-p",
                str(db["PORT"]),
                "-U",
                db["USER"],
                "-f",
                str(dump_path),
                db["NAME"],
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CommandError(f"pg_dump failed: {result.stderr}")

    def _prune_old_backups(self, retention: int) -> None:
        keys = sorted(storage.list_keys(BACKUP_PREFIX))
        stale = keys[:-retention] if retention > 0 else keys
        for key in stale:
            storage.delete(key)
            self.stdout.write(f"Pruned old backup: {key}")
        self.stdout.write(f"Retained {min(len(keys), retention)}/{len(keys)} backups")
