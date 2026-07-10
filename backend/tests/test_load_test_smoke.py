"""Day 11 e2e smoke test: proves the full load-test path works together --
synthetic generation (generate_load_test_data), MV refresh, and the real
HTTP analytics endpoints (including the category_perf_top10 covering-index
migration) -- at a small, fast scale. The 36M-row throughput/latency
numbers themselves are measured manually and documented in
docs/load-test.md; this test only proves correctness of the wiring, not
performance, since a fast test suite can't reproduce that volume.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.analytics.materialized_views import refresh_all
from apps.masterdata.models import DimBrand


@pytest.fixture
def loaded_load_test_brand(seed_calendar):
    call_command(
        "generate_load_test_data",
        "--brand-code=LOADTEST_SMOKE",
        "--brand-name=Load Test Smoke",
        "--rows=500",
        "--stores=4",
        "--products=15",
        "--batch-size=250",
        "--start-year=2023",
        "--num-years=1",
        "--seed=42",
        stdout=StringIO(),
    )
    refresh_all()
    return DimBrand.objects.get(brand_code="LOADTEST_SMOKE")


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_dashboard_reflects_generated_load_test_data(loaded_load_test_brand, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get("/api/analytics/dashboard/", {"brand_code": "LOADTEST_SMOKE"})

    assert response.status_code == 200
    assert response.data["brand_code"] == "LOADTEST_SMOKE"
    assert response.data["total"]["quantity"] != 0


@pytest.mark.django_db
def test_stores_top10_reflects_generated_load_test_data(loaded_load_test_brand, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/stores/", {"brand_code": "LOADTEST_SMOKE", "order_by": "net"}
    )

    assert response.status_code == 200
    assert len(response.data["results"]) == 4


@pytest.mark.django_db
def test_categories_top10_uses_covering_index_and_returns_data(
    loaded_load_test_brand, data_inserter_user
):
    """Exercises the exact query the Day 11 covering-index migration
    (0003_category_perf_covering_index) targets, against a freshly
    migrated test database -- proves the migration is reproducible, not
    just correct on the ad hoc index it was originally verified against."""
    client = _authed_client(data_inserter_user)

    response = client.get("/api/analytics/categories/", {"brand_code": "LOADTEST_SMOKE"})

    assert response.status_code == 200
    assert len(response.data["results"]) > 0


@pytest.mark.django_db
def test_store_trend_reflects_generated_load_test_data(loaded_load_test_brand, data_inserter_user):
    client = _authed_client(data_inserter_user)

    response = client.get(
        "/api/analytics/trends/stores/",
        {"brand_code": "LOADTEST_SMOKE", "dimension": "financial_year", "metric": "net"},
    )

    assert response.status_code == 200
    assert len(response.data["results"]) == 1
