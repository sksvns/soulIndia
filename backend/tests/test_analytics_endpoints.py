from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.ingestion.loader import load_batch
from apps.ingestion.models import UploadBatch
from apps.ingestion.pipeline import run_pipeline
from apps.ingestion.tasks import process_upload_batch
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import KILLER_GOOD_ROWS, killer_workbook


@pytest.fixture
def killer_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.fixture
def loaded_killer_data(killer_brand_and_config, data_inserter_user):
    from apps.analytics.materialized_views import refresh_all

    brand, config = killer_brand_and_config
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="test.xlsx",
        object_key="uploads/killer/menswear/test.xlsx",
    )
    result = run_pipeline(brand, config, killer_workbook(KILLER_GOOD_ROWS), "test.xlsx")
    load_batch(batch, result.rows)
    refresh_all()
    return brand


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_dashboard_endpoint_returns_correct_totals(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get("/api/analytics/dashboard/", {"brand_code": "KILLER"})

    assert response.status_code == 200
    assert response.data["total"]["net_value"] == Decimal("3055.00")
    assert response.data["brand_code"] == "KILLER"


@pytest.mark.django_db
def test_dashboard_endpoint_second_call_is_a_cache_hit(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    first = client.get("/api/analytics/dashboard/", {"brand_code": "KILLER"})
    second = client.get("/api/analytics/dashboard/", {"brand_code": "KILLER"})

    assert first.data["cache_hit"] is False
    assert second.data["cache_hit"] is True
    assert first.data["total"] == second.data["total"]


@pytest.mark.django_db
def test_stores_endpoint_returns_top10(loaded_killer_data, super_admin_user):
    client = _authed_client(super_admin_user)

    response = client.get("/api/analytics/stores/", {"brand_code": "KILLER", "order_by": "net"})

    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["store_code"] == "ESIS170"


@pytest.mark.django_db
def test_categories_endpoint_returns_top10(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get("/api/analytics/categories/", {"brand_code": "KILLER"})

    assert response.status_code == 200
    categories = {row["category"] for row in response.data["results"]}
    assert categories == {"SHIRTS", "JEANS"}


@pytest.mark.django_db
def test_unauthenticated_cannot_read_analytics(loaded_killer_data):
    client = APIClient()

    response = client.get("/api/analytics/dashboard/", {"brand_code": "KILLER"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_unknown_brand_returns_404(data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get("/api/analytics/dashboard/", {"brand_code": "NOBRAND"})

    assert response.status_code == 404


@pytest.mark.django_db
def test_filters_endpoint_returns_registry_metadata(data_inserter_user, seed_calendar):
    from io import StringIO as _StringIO

    call_command("seed_attribute_registry", stdout=_StringIO())
    client = _authed_client(data_inserter_user)

    response = client.get("/api/analytics/filters/")

    assert response.status_code == 200
    names = {row["canonical_name"] for row in response.data["filters"]}
    assert "financial_year" in names
    assert "store" in names


@pytest.mark.django_db
def test_dashboard_endpoint_applies_financial_year_and_month_filters(
    loaded_killer_data, data_inserter_user
):
    client = _authed_client(data_inserter_user)

    matching = client.get(
        "/api/analytics/dashboard/",
        {"brand_code": "KILLER", "financial_year": "23-24", "month": "4"},
    )
    no_match = client.get(
        "/api/analytics/dashboard/", {"brand_code": "KILLER", "financial_year": "24-25"}
    )

    assert matching.data["total"]["net_value"] == Decimal("3055.00")
    assert no_match.data["total"]["net_value"] == 0


@pytest.mark.django_db
def test_stores_endpoint_applies_city_and_zone_filters(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    matching = client.get(
        "/api/analytics/stores/", {"brand_code": "KILLER", "city": "DUMRAO", "zone": "EAST"}
    )
    no_match = client.get("/api/analytics/stores/", {"brand_code": "KILLER", "city": "NOSUCHCITY"})

    assert len(matching.data["results"]) == 1
    assert no_match.data["results"] == []


@pytest.mark.django_db
def test_categories_endpoint_applies_multi_value_store_filter(
    loaded_killer_data, data_inserter_user
):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/categories/", {"brand_code": "KILLER", "store": "ESIS170,ESIS999"}
    )

    categories = {row["category"] for row in response.data["results"]}
    assert categories == {"SHIRTS", "JEANS"}


@pytest.mark.django_db
def test_store_trends_endpoint_returns_series(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/trends/stores/",
        {"brand_code": "KILLER", "dimension": "financial_year", "metric": "net"},
    )

    assert response.status_code == 200
    assert response.data["results"] == [{"label": "23-24", "value": Decimal("3055.00")}]


@pytest.mark.django_db
def test_trends_endpoint_rejects_unknown_dimension(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/trends/stores/", {"brand_code": "KILLER", "dimension": "not_real"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_trends_endpoint_rejects_unknown_metric(loaded_killer_data, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/trends/categories/", {"brand_code": "KILLER", "metric": "not_real"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_category_trends_endpoint_scoped_by_category_and_store(
    loaded_killer_data, data_inserter_user
):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/trends/categories/",
        {
            "brand_code": "KILLER",
            "dimension": "season",
            "metric": "net",
            "category": "SHIRTS",
            "store": "ESIS170",
        },
    )

    assert response.status_code == 200
    labels = {row["label"] for row in response.data["results"]}
    assert labels == {"SS23"}


@pytest.mark.django_db
def test_full_upload_pipeline_refreshes_mvs_and_dashboard_reflects_new_data(
    killer_brand_and_config, data_inserter_user
):
    """End-to-end: process_upload_batch (Days 5-6) automatically refreshes
    the MVs (Day 7) so the very next dashboard read sees the new data with
    no manual refresh step."""
    from apps.ingestion import storage

    brand, config = killer_brand_and_config
    object_key = storage.build_upload_key(brand.brand_code, config.product_line, "e2e.xlsx")
    storage.put(
        object_key, killer_workbook(KILLER_GOOD_ROWS), content_type="application/octet-stream"
    )
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="e2e.xlsx",
        object_key=object_key,
    )

    process_upload_batch(batch.batch_id)

    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.LOADED

    client = _authed_client(data_inserter_user)
    response = client.get("/api/analytics/dashboard/", {"brand_code": "KILLER"})
    assert response.data["total"]["net_value"] == Decimal("3055.00")
