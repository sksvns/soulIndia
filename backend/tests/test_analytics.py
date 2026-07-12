from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.analytics import cache as analytics_cache
from apps.analytics import queries
from apps.analytics.materialized_views import refresh_all
from apps.ingestion.loader import load_batch
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import KILLER_GOOD_ROWS, killer_workbook

# KILLER_GOOD_ROWS by hand: row1 net=2124.00 mrp=2499.00 disc=375.00 (SS23,
# 23-24, April); row2 net=2450.00 mrp=3099.00 disc=649.00 (AW22, 23-24,
# April); row3 (return) net=-1519.00 mrp=-1899.00 disc=-380.00 (SS23, 23-24,
# April). Hand totals: mrp=2499+3099-1899=3699.00, net=2124+2450-1519=3055.00,
# discount=375+649-380=644.00, qty=1+1-1=1.
EXPECTED_TOTAL_MRP = Decimal("3699.00")
EXPECTED_TOTAL_NET = Decimal("3055.00")
EXPECTED_TOTAL_DISCOUNT = Decimal("644.00")
EXPECTED_TOTAL_QTY = 1

# SS23 season: row1 (net 2124, mrp 2499, disc 375) + row3 return (net -1519,
# mrp -1899, disc -380) => net=605.00, mrp=600.00, disc=-5.00, qty=0.
EXPECTED_SS23_NET = Decimal("605.00")
EXPECTED_SS23_MRP = Decimal("600.00")


@pytest.fixture
def killer_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.fixture
def loaded_killer_data(killer_brand_and_config, data_inserter_user):
    from apps.ingestion.models import UploadBatch

    brand, config = killer_brand_and_config
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="test.xlsx",
        object_key="uploads/killer/menswear/test.xlsx",
    )
    result = run_pipeline(brand, config, killer_workbook(KILLER_GOOD_ROWS), "test.xlsx")
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return brand


@pytest.mark.django_db
def test_dashboard_summary_matches_hand_computed_totals_to_the_paisa(loaded_killer_data):
    brand = loaded_killer_data

    result = queries.dashboard_summary(brand.brand_id)

    assert result["total"]["mrp_value"] == EXPECTED_TOTAL_MRP
    assert result["total"]["net_value"] == EXPECTED_TOTAL_NET
    assert result["total"]["discount_value"] == EXPECTED_TOTAL_DISCOUNT
    assert result["total"]["quantity"] == EXPECTED_TOTAL_QTY

    by_season = {row["season_code"]: row for row in result["by_season"]}
    assert set(by_season) == {"SS23", "AW22"}
    assert by_season["SS23"]["net_value"] == EXPECTED_SS23_NET
    assert by_season["SS23"]["mrp_value"] == EXPECTED_SS23_MRP
    assert by_season["AW22"]["net_value"] == Decimal("2450.00")


@pytest.mark.django_db
def test_dashboard_summary_filters_by_financial_year_and_month(loaded_killer_data):
    brand = loaded_killer_data

    matching = queries.dashboard_summary(brand.brand_id, {"financial_year": "23-24", "month": 4})
    assert matching["total"]["net_value"] == EXPECTED_TOTAL_NET

    no_match_fy = queries.dashboard_summary(brand.brand_id, {"financial_year": "24-25"})
    assert no_match_fy["total"]["net_value"] == 0

    no_match_month = queries.dashboard_summary(brand.brand_id, {"month": 5})
    assert no_match_month["total"]["net_value"] == 0


@pytest.mark.django_db
def test_store_perf_top10_orders_by_requested_column(loaded_killer_data):
    brand = loaded_killer_data

    by_net = queries.store_perf_top10(brand.brand_id, order_by="net")
    assert len(by_net) == 1  # all 3 rows are the same single store, ESIS170
    assert by_net[0]["store_code"] == "ESIS170"
    assert by_net[0]["net_value"] == EXPECTED_TOTAL_NET
    assert by_net[0]["mrp_value"] == EXPECTED_TOTAL_MRP
    assert by_net[0]["discount_pct"] is not None


@pytest.mark.django_db
def test_category_perf_top10_reflects_2_level_hierarchy_and_store_filter(loaded_killer_data):
    brand = loaded_killer_data

    results = queries.category_perf_top10(brand.brand_id, order_by="net")
    categories = {row["category"] for row in results}
    assert categories == {"SHIRTS", "JEANS"}

    filtered = queries.category_perf_top10(brand.brand_id, {"store": ["ESIS170"]})
    assert len(filtered) == 2  # SHIRTS and JEANS, same store

    no_match = queries.category_perf_top10(brand.brand_id, {"store": ["NOSUCHSTORE"]})
    assert no_match == []


@pytest.mark.django_db
def test_cache_get_or_compute_is_a_miss_then_a_hit(loaded_killer_data):
    brand = loaded_killer_data
    calls = []

    def compute():
        calls.append(1)
        return {"value": 42}

    result1, hit1, cached_at1 = analytics_cache.get_or_compute(
        brand.brand_id, "test_endpoint", {}, compute
    )
    result2, hit2, cached_at2 = analytics_cache.get_or_compute(
        brand.brand_id, "test_endpoint", {}, compute
    )

    assert hit1 is False
    assert hit2 is True
    assert result1 == result2 == {"value": 42}
    assert len(calls) == 1  # compute_fn only ran once
    assert cached_at1 == cached_at2  # the hit reads back the miss's timestamp unchanged


@pytest.mark.django_db
def test_cache_bust_invalidates_previously_cached_results(loaded_killer_data):
    brand = loaded_killer_data
    calls = []

    def compute():
        calls.append(1)
        return {"value": len(calls)}

    result1, _, _ = analytics_cache.get_or_compute(brand.brand_id, "test_endpoint", {}, compute)
    analytics_cache.bust(brand.brand_id)
    result2, hit2, _ = analytics_cache.get_or_compute(brand.brand_id, "test_endpoint", {}, compute)

    assert hit2 is False  # bust made the old cache entry unreachable
    assert result1 != result2
    assert len(calls) == 2


@pytest.mark.django_db
def test_cache_force_refresh_bypasses_a_hit_and_updates_cached_at(loaded_killer_data):
    """The manual refresh button: force_refresh=True always recomputes,
    even though a valid cache entry exists, and the new cached_at reflects
    that fresh computation."""
    brand = loaded_killer_data
    calls = []

    def compute():
        calls.append(1)
        return {"value": len(calls)}

    result1, hit1, cached_at1 = analytics_cache.get_or_compute(
        brand.brand_id, "test_endpoint", {}, compute
    )
    result2, hit2, cached_at2 = analytics_cache.get_or_compute(
        brand.brand_id, "test_endpoint", {}, compute, force_refresh=True
    )

    assert hit1 is False
    assert hit2 is False  # force_refresh always looks like a miss
    assert result1 != result2
    assert len(calls) == 2
    assert cached_at2 >= cached_at1


@pytest.mark.django_db
def test_cache_is_scoped_per_brand(loaded_killer_data):
    """Busting one brand's cache must not affect another brand's."""
    from apps.masterdata.models import DimBrand

    pepe = DimBrand.objects.get(brand_code="PEPE")
    calls = []

    def compute():
        calls.append(1)
        return {"value": len(calls)}

    analytics_cache.get_or_compute(loaded_killer_data.brand_id, "test_endpoint", {}, compute)
    analytics_cache.bust(pepe.brand_id)
    _, hit, _ = analytics_cache.get_or_compute(
        loaded_killer_data.brand_id, "test_endpoint", {}, compute
    )

    assert hit is True  # unaffected by pepe's bust
