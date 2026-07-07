import tempfile
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.ingestion import storage
from apps.ingestion.backfill import run_backfill_pipeline
from apps.ingestion.models import UploadBatch
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import KILLER_BAD_ROWS, KILLER_GOOD_ROWS, killer_workbook


@pytest.fixture
def killer_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


def _write_temp_xlsx(workbook_buffer):
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.write(workbook_buffer.read())
    tmp.close()
    return tmp.name


@pytest.mark.django_db
def test_run_backfill_pipeline_splits_good_rows_from_bad(killer_brand_and_config):
    brand, config = killer_brand_and_config
    mixed_rows = KILLER_GOOD_ROWS + KILLER_BAD_ROWS
    workbook = killer_workbook(mixed_rows)

    result = run_backfill_pipeline(brand, config, workbook, "mixed.xlsx")

    assert result.total_rows == len(mixed_rows)
    assert len(result.valid_rows) == len(KILLER_GOOD_ROWS)
    assert {row["invoice_no"] for row in result.valid_rows} == {"81", "280", "417"}
    assert len(result.errors) > 0
    # Bad rows resolved to no store_id/product_id at all -- proves Phase B
    # never ran on them.
    bad_invoice_nos = {"82", "83", "84", "85"}
    assert not any(row.get("invoice_no") in bad_invoice_nos for row in result.valid_rows)


@pytest.mark.django_db
def test_run_backfill_pipeline_with_all_good_rows_has_no_errors(killer_brand_and_config):
    brand, config = killer_brand_and_config
    workbook = killer_workbook(KILLER_GOOD_ROWS)

    result = run_backfill_pipeline(brand, config, workbook, "good.xlsx")

    assert result.errors == []
    assert len(result.valid_rows) == len(KILLER_GOOD_ROWS)
    for row in result.valid_rows:
        assert row["store_id"] is not None
        assert row["product_id"] is not None


@pytest.mark.django_db
def test_backfill_command_loads_good_rows_and_writes_bad_rows_csv(
    killer_brand_and_config, super_admin_user, tmp_path
):
    brand, config = killer_brand_and_config
    mixed_rows = KILLER_GOOD_ROWS + KILLER_BAD_ROWS
    file_path = _write_temp_xlsx(killer_workbook(mixed_rows))
    csv_out = str(tmp_path / "bad_rows.csv")

    call_command(
        "backfill_historical",
        "KILLER",
        "menswear",
        file_path,
        f"--user-email={super_admin_user.email}",
        f"--csv-out={csv_out}",
        stdout=StringIO(),
    )

    batch = UploadBatch.objects.get(brand=brand)
    assert batch.status == UploadBatch.Status.LOADED
    assert batch.row_count == len(KILLER_GOOD_ROWS)
    # >= not ==: one bad row (the unparseable date) trips both a coercion
    # error and a required-field-missing error for sale_date -- a row can
    # have more than one error, so error_count isn't 1:1 with bad rows.
    assert batch.error_count >= len(KILLER_BAD_ROWS)
    assert batch.error_report_key is not None
    assert batch.uploaded_by == super_admin_user

    from apps.ingestion.models import FactSales

    assert FactSales.objects.filter(batch=batch).count() == len(KILLER_GOOD_ROWS)
    assert set(FactSales.objects.filter(batch=batch).values_list("invoice_no", flat=True)) == {
        "81",
        "280",
        "417",
    }

    # CSV landed both in object storage and at the local --csv-out path,
    # and covers all 4 bad rows (by their distinct invoice numbers landing
    # in the source_row_no's row_no -- checked indirectly via error count
    # per row_no below).
    stored_csv = storage.get(batch.error_report_key).read().decode("utf-8")
    assert "required field is missing" in stored_csv or "return row" in stored_csv
    distinct_bad_row_nos = {line.split(",")[0] for line in stored_csv.splitlines()[1:]}
    assert len(distinct_bad_row_nos) == len(KILLER_BAD_ROWS)
    with open(csv_out, "rb") as f:
        local_csv = f.read().decode("utf-8")
    assert local_csv == stored_csv


@pytest.mark.django_db
def test_backfill_command_with_all_bad_rows_loads_nothing_and_raises(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    file_path = _write_temp_xlsx(killer_workbook(KILLER_BAD_ROWS))

    with pytest.raises(CommandError):
        call_command(
            "backfill_historical",
            "KILLER",
            "menswear",
            file_path,
            f"--user-email={super_admin_user.email}",
            stdout=StringIO(),
        )

    batch = UploadBatch.objects.get(brand=brand)
    assert batch.status == UploadBatch.Status.FAILED
    assert batch.error_count >= len(KILLER_BAD_ROWS)


@pytest.mark.django_db
def test_backfill_command_unknown_user_raises_clean_error(killer_brand_and_config):
    file_path = _write_temp_xlsx(killer_workbook(KILLER_GOOD_ROWS))

    with pytest.raises(CommandError):
        call_command(
            "backfill_historical",
            "KILLER",
            "menswear",
            file_path,
            "--user-email=nosuchuser@example.com",
            stdout=StringIO(),
        )


@pytest.mark.django_db
def test_backfill_command_second_run_on_same_slice_requires_super_admin(
    killer_brand_and_config, super_admin_user, data_inserter_user
):
    """First backfill loads into an empty slice (no gate). A second backfill
    touching the *same* (store, month) is an alteration (ADR-0003) -- proves
    the backfill command reuses loader.load_batch's existing gate rather
    than bypassing it."""
    brand, config = killer_brand_and_config
    file_path = _write_temp_xlsx(killer_workbook(KILLER_GOOD_ROWS))

    call_command(
        "backfill_historical",
        "KILLER",
        "menswear",
        file_path,
        f"--user-email={super_admin_user.email}",
        stdout=StringIO(),
    )

    with pytest.raises(CommandError, match="Super Admin"):
        call_command(
            "backfill_historical",
            "KILLER",
            "menswear",
            file_path,
            f"--user-email={data_inserter_user.email}",
            stdout=StringIO(),
        )
