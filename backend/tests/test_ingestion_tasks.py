from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion import storage
from apps.ingestion.models import UploadBatch
from apps.ingestion.tasks import process_upload_batch
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import KILLER_BAD_ROWS, KILLER_GOOD_ROWS, killer_workbook


@pytest.fixture
def killer_brand_and_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


def _upload_and_create_batch(brand, config, user, workbook, filename):
    object_key = storage.build_upload_key(brand.brand_code, config.product_line, filename)
    storage.put(object_key, workbook, content_type="application/octet-stream")
    return UploadBatch.objects.create(
        brand=brand, config=config, uploaded_by=user, file_name=filename, object_key=object_key
    )


@pytest.mark.django_db
def test_process_upload_batch_on_a_clean_file_reaches_validating_with_row_count(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _upload_and_create_batch(
        brand, config, data_inserter_user, killer_workbook(KILLER_GOOD_ROWS), "april.xlsx"
    )

    process_upload_batch(batch.batch_id)

    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.VALIDATING
    assert batch.row_count == 3
    assert batch.error_count == 0
    assert batch.started_at is not None
    # Day 6 continues from here to actually load into fact_sales.
    assert DimStore.objects.filter(brand=brand, store_code="ESIS170").exists()
    assert DimProduct.objects.filter(brand=brand).exists()


@pytest.mark.django_db
def test_process_upload_batch_on_a_bad_file_fails_with_downloadable_error_report(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _upload_and_create_batch(
        brand, config, data_inserter_user, killer_workbook(KILLER_BAD_ROWS), "bad.xlsx"
    )

    process_upload_batch(batch.batch_id)

    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.FAILED
    assert batch.error_count > 0
    assert batch.error_report_key == f"error-reports/{batch.batch_id}.csv"
    assert batch.finished_at is not None

    report_bytes = storage.get(batch.error_report_key).read().decode()
    assert "row_no,field,value,reason" in report_bytes
    assert "zero quantity" in report_bytes


@pytest.mark.django_db
def test_process_upload_batch_on_a_bad_file_creates_no_dimension_rows(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _upload_and_create_batch(
        brand, config, data_inserter_user, killer_workbook(KILLER_BAD_ROWS), "bad.xlsx"
    )

    process_upload_batch(batch.batch_id)

    assert not DimStore.objects.filter(brand=brand).exists()
    assert not DimProduct.objects.filter(brand=brand).exists()
