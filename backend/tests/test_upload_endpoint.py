from io import StringIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.ingestion.models import UploadBatch

SYNTHETIC_KILLER_CSV = (
    b"NEW DATE,MONTH,SEASON,F. YEAR,BILL NO INVOICE NO,STORE CODE,NAME,"
    b"NEW EAN CODE,ITEM NAME,MAIN CATEGORY,CATEGORY,MRP,QTY SALE,"
    b"MRP SALE VALUE,NET SALE VALUE,DISCOUNT VALUE,SUPER SECRET FIELD\n"
    b"2023-04-05,APRIL,SS23,23-24,21,ESIS170,Aadarsh,8905646747185,"
    b"KT-5410 RNHS RST,T-SHIRTS,T-SHIRTS,1399,1,1399,1190,209,mystery-value\n"
)


@pytest.fixture
def killer_upload_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
@patch("apps.ingestion.views.process_upload_batch.delay")
def test_upload_creates_batch_and_enqueues_task(
    mock_delay, killer_upload_config, data_inserter_user
):
    client = _authed_client(data_inserter_user)
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )

    assert response.status_code == 201
    batch = UploadBatch.objects.get(pk=response.data["batch_id"])
    assert batch.status == UploadBatch.Status.RECEIVED
    assert batch.brand.brand_code == "KILLER"
    assert batch.uploaded_by == data_inserter_user
    assert batch.file_name == "april.csv"
    mock_delay.assert_called_once_with(batch.batch_id)


@pytest.mark.django_db
@patch("apps.ingestion.views.process_upload_batch.delay")
def test_uploaded_raw_file_is_stored_immutably_and_matches_original_bytes(
    mock_delay, killer_upload_config, data_inserter_user
):
    from apps.ingestion import storage

    client = _authed_client(data_inserter_user)
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )

    batch = UploadBatch.objects.get(pk=response.data["batch_id"])
    stored_bytes = storage.get(batch.object_key).read()
    assert stored_bytes == SYNTHETIC_KILLER_CSV


@pytest.mark.django_db
def test_upload_rejects_unknown_brand(killer_upload_config, data_inserter_user):
    client = _authed_client(data_inserter_user)
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "NOBRAND", "product_line": "menswear"},
        format="multipart",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_upload_rejects_unmapped_product_line(killer_upload_config, data_inserter_user):
    client = _authed_client(data_inserter_user)
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "womenswear"},
        format="multipart",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_upload_rejects_unsupported_file_extension(killer_upload_config, data_inserter_user):
    client = _authed_client(data_inserter_user)
    upload = SimpleUploadedFile("april.pdf", b"not a spreadsheet", content_type="application/pdf")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_upload_rejects_missing_fields(killer_upload_config, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.post("/api/ingestion/uploads/", {}, format="multipart")

    assert response.status_code == 400


@pytest.mark.django_db
def test_unauthenticated_cannot_upload(killer_upload_config):
    client = APIClient()
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )

    assert response.status_code == 401


@pytest.mark.django_db
@patch("apps.ingestion.views.process_upload_batch.delay")
def test_super_admin_can_also_upload(mock_delay, killer_upload_config, super_admin_user):
    client = _authed_client(super_admin_user)
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")

    response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )

    assert response.status_code == 201


@pytest.mark.django_db
@patch("apps.ingestion.views.process_upload_batch.delay")
def test_upload_detail_view_returns_batch_status(
    mock_delay, killer_upload_config, data_inserter_user
):
    client = _authed_client(data_inserter_user)
    upload = SimpleUploadedFile("april.csv", SYNTHETIC_KILLER_CSV, content_type="text/csv")
    create_response = client.post(
        "/api/ingestion/uploads/",
        {"file": upload, "brand_code": "KILLER", "product_line": "menswear"},
        format="multipart",
    )
    batch_id = create_response.data["batch_id"]

    response = client.get(f"/api/ingestion/uploads/{batch_id}/")

    assert response.status_code == 200
    assert response.data["batch_id"] == batch_id
    assert response.data["status"] == "received"
    assert response.data["brand_code"] == "KILLER"
    assert "failure_reason" in response.data  # visible for system/permission failures too
