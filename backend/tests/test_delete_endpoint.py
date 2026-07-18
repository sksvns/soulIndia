from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.ingestion.loader import load_batch
from apps.ingestion.models import DataAlterationAudit, FactSales, UploadBatch
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import KILLER_GOOD_ROWS, killer_workbook


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


def _load_killer_good_rows(brand, config, user):
    result = run_pipeline(brand, config, killer_workbook(KILLER_GOOD_ROWS), "test.xlsx")
    assert result.ok, result.errors
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=user,
        file_name="test.xlsx",
        object_key="uploads/killer/menswear/test.xlsx",
    )
    load_batch(batch, result.rows)
    return batch


@pytest.mark.django_db
def test_preview_endpoint_returns_summary_of_matching_data(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    _load_killer_good_rows(brand, config, data_inserter_user)
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/ingestion/delete-preview/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "23-24", "month": 4},
    )

    assert response.status_code == 200
    assert response.data["row_count"] == 3
    assert response.data["store_count"] == 1
    assert response.data["total_net_value"] == Decimal("3055.00")


@pytest.mark.django_db
def test_preview_endpoint_returns_zero_for_no_match(killer_brand_and_config, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/ingestion/delete-preview/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "23-24", "month": 4},
    )

    assert response.status_code == 200
    assert response.data["row_count"] == 0
    assert response.data["total_net_value"] is None


@pytest.mark.django_db
def test_preview_endpoint_rejects_malformed_financial_year(
    killer_brand_and_config, data_inserter_user
):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/ingestion/delete-preview/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "2023", "month": 4},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_preview_endpoint_rejects_out_of_range_month(killer_brand_and_config, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/ingestion/delete-preview/",
        {
            "brand_code": "KILLER",
            "product_line": "menswear",
            "financial_year": "23-24",
            "month": 13,
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_preview_endpoint_404s_for_unknown_brand(killer_brand_and_config, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/ingestion/delete-preview/",
        {
            "brand_code": "NOPE",
            "product_line": "menswear",
            "financial_year": "23-24",
            "month": 4,
        },
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_endpoint_rejects_data_inserter_and_data_survives(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    _load_killer_good_rows(brand, config, data_inserter_user)
    client = _authed_client(data_inserter_user)

    response = client.post(
        "/api/ingestion/delete/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "23-24", "month": 4},
        format="json",
    )

    assert response.status_code == 403
    assert FactSales.objects.filter(brand=brand).count() == 3
    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is False
    assert audit.action == DataAlterationAudit.Action.DELETE_FILTERED


@pytest.mark.django_db
def test_delete_endpoint_accepts_super_admin_and_removes_data(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    _load_killer_good_rows(brand, config, super_admin_user)
    client = _authed_client(super_admin_user)

    response = client.post(
        "/api/ingestion/delete/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "23-24", "month": 4},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["deleted_count"] == 3
    assert not FactSales.objects.filter(brand=brand).exists()
    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is True
    assert audit.action == DataAlterationAudit.Action.DELETE_FILTERED


@pytest.mark.django_db
def test_delete_endpoint_404s_for_unknown_product_line(
    killer_brand_and_config, super_admin_user
):
    client = _authed_client(super_admin_user)

    response = client.post(
        "/api/ingestion/delete/",
        {
            "brand_code": "KILLER",
            "product_line": "does-not-exist",
            "financial_year": "23-24",
            "month": 4,
        },
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_unauthenticated_cannot_preview_or_delete(killer_brand_and_config):
    client = APIClient()

    preview_response = client.get(
        "/api/ingestion/delete-preview/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "23-24", "month": 4},
    )
    delete_response = client.post(
        "/api/ingestion/delete/",
        {"brand_code": "KILLER", "product_line": "menswear", "financial_year": "23-24", "month": 4},
        format="json",
    )

    assert preview_response.status_code == 401
    assert delete_response.status_code == 401
