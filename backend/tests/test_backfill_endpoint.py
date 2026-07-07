from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.ingestion import storage
from apps.ingestion.models import FactSales, UploadBatch
from apps.ingestion.tasks import process_backfill_batch, process_upload_batch
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import KILLER_BAD_ROWS, KILLER_GOOD_ROWS, killer_workbook


@pytest.fixture
def killer_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _xlsx_upload(rows, filename="backfill.xlsx"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        filename,
        killer_workbook(rows).read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@pytest.mark.django_db
def test_backfill_endpoint_rejects_data_inserter(killer_brand_and_config, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.post(
        "/api/ingestion/backfill/",
        {
            "file": _xlsx_upload(KILLER_GOOD_ROWS),
            "brand_code": "KILLER",
            "product_line": "menswear",
        },
        format="multipart",
    )

    assert response.status_code == 403
    assert not UploadBatch.objects.exists()


@pytest.mark.django_db
@patch("apps.ingestion.views.process_backfill_batch.delay")
def test_backfill_endpoint_accepts_super_admin_and_enqueues_task(
    mock_delay, killer_brand_and_config, super_admin_user
):
    client = _authed_client(super_admin_user)

    response = client.post(
        "/api/ingestion/backfill/",
        {
            "file": _xlsx_upload(KILLER_GOOD_ROWS),
            "brand_code": "KILLER",
            "product_line": "menswear",
        },
        format="multipart",
    )

    assert response.status_code == 201
    batch = UploadBatch.objects.get(pk=response.data["batch_id"])
    assert batch.status == UploadBatch.Status.RECEIVED
    assert batch.uploaded_by == super_admin_user
    mock_delay.assert_called_once_with(batch.batch_id)


@pytest.mark.django_db
def test_backfill_endpoint_end_to_end_loads_good_rows_and_reports_bad_ones(
    killer_brand_and_config, super_admin_user
):
    client = _authed_client(super_admin_user)
    mixed_rows = KILLER_GOOD_ROWS + KILLER_BAD_ROWS

    create_response = client.post(
        "/api/ingestion/backfill/",
        {"file": _xlsx_upload(mixed_rows), "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )
    batch_id = create_response.data["batch_id"]

    # Normally run by the celery worker; called directly here (same pattern
    # as test_ingestion_tasks.py) to exercise the real task synchronously.
    process_backfill_batch(batch_id)

    batch = UploadBatch.objects.get(pk=batch_id)
    assert batch.status == UploadBatch.Status.LOADED
    assert batch.row_count == len(KILLER_GOOD_ROWS)
    assert batch.error_count >= len(KILLER_BAD_ROWS)
    assert batch.error_report_key is not None
    assert FactSales.objects.filter(batch=batch).count() == len(KILLER_GOOD_ROWS)

    status_response = client.get(f"/api/ingestion/uploads/{batch_id}/")
    assert status_response.status_code == 200
    assert status_response.data["status"] == "loaded"
    assert status_response.data["row_count"] == len(KILLER_GOOD_ROWS)
    assert status_response.data["error_count"] == batch.error_count

    report_response = client.get(f"/api/ingestion/uploads/{batch_id}/error-report/")
    assert report_response.status_code == 200
    assert report_response["Content-Type"] == "text/csv"
    body = report_response.content.decode("utf-8")
    assert "row_no,field,value,reason" in body
    assert "required field is missing" in body or "return row" in body


@pytest.mark.django_db
def test_error_report_download_returns_404_when_batch_has_no_errors(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    object_key = storage.build_upload_key(brand.brand_code, config.product_line, "clean.xlsx")
    storage.put(
        object_key, killer_workbook(KILLER_GOOD_ROWS), content_type="application/octet-stream"
    )
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="clean.xlsx",
        object_key=object_key,
    )
    process_upload_batch(batch.batch_id)
    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.LOADED  # sanity: no errors at all

    client = _authed_client(data_inserter_user)
    response = client.get(f"/api/ingestion/uploads/{batch.batch_id}/error-report/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_error_report_download_works_for_a_regular_failed_upload_too(
    killer_brand_and_config, data_inserter_user
):
    """The download endpoint isn't backfill-specific -- it fixes the same
    gap for the regular all-or-nothing upload path, which already stored
    error_report_key but had no way to fetch it."""
    brand, config = killer_brand_and_config
    object_key = storage.build_upload_key(brand.brand_code, config.product_line, "bad.xlsx")
    storage.put(
        object_key, killer_workbook(KILLER_BAD_ROWS), content_type="application/octet-stream"
    )
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="bad.xlsx",
        object_key=object_key,
    )
    process_upload_batch(batch.batch_id)
    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.FAILED

    client = _authed_client(data_inserter_user)
    response = client.get(f"/api/ingestion/uploads/{batch.batch_id}/error-report/")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "row_no,field,value,reason" in body


@pytest.mark.django_db
def test_unauthenticated_cannot_use_backfill_or_download_report(killer_brand_and_config):
    client = APIClient()

    backfill_response = client.post(
        "/api/ingestion/backfill/",
        {
            "file": _xlsx_upload(KILLER_GOOD_ROWS),
            "brand_code": "KILLER",
            "product_line": "menswear",
        },
        format="multipart",
    )
    report_response = client.get("/api/ingestion/uploads/1/error-report/")

    assert backfill_response.status_code == 401
    assert report_response.status_code == 401
