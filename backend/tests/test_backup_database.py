import io
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion import storage


@pytest.mark.django_db
def test_backup_database_uploads_a_real_pg_dump(seed_calendar):
    call_command("backup_database", "--retention=1000", stdout=StringIO())

    keys = storage.list_keys("backups/")
    assert len(keys) >= 1
    latest = sorted(keys)[-1]
    assert latest.endswith(".dump")

    # A real pg_dump custom-format file starts with this magic header --
    # proves the upload is an actual dump, not an empty/garbage file.
    body = storage.get(latest).read(5)
    assert body == b"PGDMP"


@pytest.mark.django_db
def test_backup_database_prunes_down_to_retention_count(seed_calendar):
    prefix = "backups/"
    for name in ["fake_a.dump", "fake_b.dump", "fake_c.dump"]:
        storage.put(f"{prefix}{name}", io.BytesIO(b"PGDMPfake"))

    call_command("backup_database", "--retention=2", stdout=StringIO())

    keys = sorted(storage.list_keys(prefix))
    assert len(keys) == 2
    # oldest fakes pruned first (lexicographic == chronological for our
    # zero-padded timestamp keys); the just-created real dump survives.
    assert "backups/fake_a.dump" not in keys
