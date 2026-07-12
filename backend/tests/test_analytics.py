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
from tests.ingestion_fixtures import (
    KILLER_GOOD_ROWS,
    KILLER_TREND_ROWS,
    PEPE_GOOD_ROWS,
    killer_workbook,
    pepe_workbook,
)

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


@pytest.fixture
def loaded_killer_and_pepe_data(loaded_killer_data, killer_brand_and_config, data_inserter_user):
    """Two different brands both loaded, for testing the dashboard's
    "all brands combined" default (client feedback) -- distinct from
    every other fixture here, which only ever loads one brand."""
    from apps.ingestion.models import UploadBatch

    pepe = DimBrand.objects.get(brand_code="PEPE")
    pepe_config = BrandUploadConfig.objects.get(brand=pepe)
    batch = UploadBatch.objects.create(
        brand=pepe,
        config=pepe_config,
        uploaded_by=data_inserter_user,
        file_name="pepe.xlsx",
        object_key="uploads/pepe/menswear/pepe.xlsx",
    )
    result = run_pipeline(pepe, pepe_config, pepe_workbook(PEPE_GOOD_ROWS), "pepe.xlsx")
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return loaded_killer_data, pepe


@pytest.mark.django_db
def test_dashboard_summary_matches_hand_computed_totals_to_the_paisa(loaded_killer_data):
    brand = loaded_killer_data

    result = queries.dashboard_summary([brand.brand_id])

    assert result["total"]["mrp_value"] == EXPECTED_TOTAL_MRP
    assert result["total"]["net_value"] == EXPECTED_TOTAL_NET
    assert result["total"]["discount_value"] == EXPECTED_TOTAL_DISCOUNT
    assert result["total"]["quantity"] == EXPECTED_TOTAL_QTY

    # All of KILLER_GOOD_ROWS falls in the same financial year (23-24), so
    # the year breakdown is a single row matching the brand-wide total --
    # multi-year grouping itself is covered by the dedicated test below.
    assert result["granularity"] == "year"
    by_year = {row["label"]: row for row in result["breakdown"]}
    assert set(by_year) == {"23-24"}
    assert by_year["23-24"]["net_value"] == EXPECTED_TOTAL_NET
    assert by_year["23-24"]["mrp_value"] == EXPECTED_TOTAL_MRP


@pytest.mark.django_db
def test_dashboard_summary_filters_by_financial_year_and_month(loaded_killer_data):
    brand = loaded_killer_data

    matching = queries.dashboard_summary([brand.brand_id], {"financial_year": "23-24", "month": 4})
    assert matching["total"]["net_value"] == EXPECTED_TOTAL_NET

    no_match_fy = queries.dashboard_summary([brand.brand_id], {"financial_year": "24-25"})
    assert no_match_fy["total"]["net_value"] == 0

    no_match_month = queries.dashboard_summary([brand.brand_id], {"month": 5})
    assert no_match_month["total"]["net_value"] == 0


@pytest.mark.django_db
def test_dashboard_summary_switches_to_monthly_breakdown_when_only_year_selected(
    loaded_trend_data,
):
    """Client feedback: picking a year should chart that year's months,
    not stay flat at a single year-wide bar."""
    brand = loaded_trend_data

    result = queries.dashboard_summary([brand.brand_id], {"financial_year": "23-24"})

    assert result["granularity"] == "month"
    by_month = {row["label"]: row for row in result["breakdown"]}
    assert list(by_month) == ["April", "July", "October"]  # fiscal chronological order
    assert by_month["April"]["net_value"] == Decimal("1500.00")  # rows 501 + 505
    assert by_month["July"]["net_value"] == Decimal("1800.00")  # row 502
    assert by_month["October"]["net_value"] == Decimal("1500.00")  # row 503
    assert result["total"]["net_value"] == Decimal("4800.00")


@pytest.mark.django_db
def test_dashboard_summary_switches_to_weekly_breakdown_when_year_and_month_selected(
    loaded_killer_data,
):
    """Client feedback: picking a year AND a month should chart that
    month's weeks. KILLER_GOOD_ROWS' 3 rows land in 3 different ISO weeks
    of April 2023 (Apr 5, Apr 15, Apr 26), so this also proves the weekly
    fact_sales query -- the one deliberate exception to querying MVs only
    -- returns the same rows/totals the MV-backed paths would."""
    brand = loaded_killer_data

    result = queries.dashboard_summary([brand.brand_id], {"financial_year": "23-24", "month": 4})

    assert result["granularity"] == "week"
    labels = [row["label"] for row in result["breakdown"]]
    assert labels == ["Week 1", "Week 2", "Week 3"]
    assert result["breakdown"][0]["net_value"] == Decimal("2124.00")  # Apr 5
    assert result["breakdown"][1]["net_value"] == Decimal("-1519.00")  # Apr 15 return
    assert result["breakdown"][2]["net_value"] == Decimal("2450.00")  # Apr 26
    assert result["total"]["net_value"] == EXPECTED_TOTAL_NET


@pytest.mark.django_db
def test_dashboard_summary_weekly_breakdown_still_respects_category_filter(loaded_killer_data):
    """The weekly path's own filter engine (fact_sales joined to
    dim_product/dim_store) must narrow the same way the MV-backed paths
    do, not just ignore category/store once granularity flips to week."""
    brand = loaded_killer_data

    shirts_only = queries.dashboard_summary(
        [brand.brand_id], {"financial_year": "23-24", "month": 4, "category": "SHIRTS"}
    )
    assert shirts_only["granularity"] == "week"
    # Apr 5 (SHIRTS, net 2124) + Apr 15 return (SHIRTS, net -1519); Apr 26 is JEANS.
    assert shirts_only["total"]["net_value"] == Decimal("605.00")
    assert len(shirts_only["breakdown"]) == 2


@pytest.fixture
def loaded_trend_data(killer_brand_and_config, data_inserter_user):
    from apps.ingestion.models import UploadBatch

    brand, config = killer_brand_and_config
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="trend.xlsx",
        object_key="uploads/killer/menswear/trend.xlsx",
    )
    result = run_pipeline(brand, config, killer_workbook(KILLER_TREND_ROWS), "trend.xlsx")
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return brand


@pytest.mark.django_db
def test_dashboard_summary_groups_by_financial_year_not_season(loaded_trend_data):
    """Client feedback: the dashboard chart's baseline is year, not season
    (see tests/test_trends.py's KILLER_TREND_ROWS hand-computation for the
    row-by-row numbers this is built from)."""
    brand = loaded_trend_data

    result = queries.dashboard_summary([brand.brand_id])

    assert result["granularity"] == "year"
    by_year = {row["label"]: row for row in result["breakdown"]}
    assert set(by_year) == {"23-24", "24-25"}
    assert by_year["23-24"]["net_value"] == Decimal("4800.00")
    assert by_year["23-24"]["mrp_value"] == Decimal("5000.00")
    assert by_year["24-25"]["net_value"] == Decimal("3000.00")
    assert by_year["24-25"]["mrp_value"] == Decimal("3000.00")


@pytest.mark.django_db
def test_dashboard_summary_filters_by_category_sub_category_and_store(loaded_trend_data):
    """The dashboard's new 6-field filter set (client feedback) includes
    category/sub_category/store -- mv_sales_summary couldn't answer these
    at all (no grain for them); mv_category_perf can."""
    brand = loaded_trend_data

    shirts_only = queries.dashboard_summary([brand.brand_id], {"category": "SHIRTS"})
    assert shirts_only["total"]["net_value"] == Decimal("6300.00")  # rows 501,502,504,505

    jeans_only = queries.dashboard_summary([brand.brand_id], {"category": "JEANS"})
    assert jeans_only["total"]["net_value"] == Decimal("1500.00")  # row 503

    one_store = queries.dashboard_summary([brand.brand_id], {"store": "ESIS999"})
    assert one_store["total"]["net_value"] == Decimal("500.00")  # row 505 only


@pytest.mark.django_db
def test_dashboard_filter_options_reflects_real_data_only(loaded_trend_data):
    brand = loaded_trend_data

    options = queries.dashboard_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]
    assert set(options["categories"]) == {"SHIRTS", "JEANS"}
    assert {s["store_code"] for s in options["stores"]} == {"ESIS170", "ESIS999"}


@pytest.mark.django_db
def test_dashboard_summary_combines_every_brand_when_no_single_brand_requested(
    loaded_killer_and_pepe_data,
):
    """Client feedback: the dashboard's default view is every active
    brand combined, not one brand you must pick first."""
    killer, pepe = loaded_killer_and_pepe_data

    killer_only = queries.dashboard_summary([killer.brand_id])
    pepe_only = queries.dashboard_summary([pepe.brand_id])
    combined = queries.dashboard_summary([killer.brand_id, pepe.brand_id])

    assert combined["total"]["net_value"] == (
        killer_only["total"]["net_value"] + pepe_only["total"]["net_value"]
    )
    assert combined["total"]["quantity"] == (
        killer_only["total"]["quantity"] + pepe_only["total"]["quantity"]
    )
    # Both brands' years appear in the combined breakdown, not just one.
    combined_years = {row["label"] for row in combined["breakdown"]}
    assert combined_years >= {row["label"] for row in killer_only["breakdown"]}
    assert combined_years >= {row["label"] for row in pepe_only["breakdown"]}


@pytest.mark.django_db
def test_dashboard_filter_options_combines_every_brand_when_no_single_brand_requested(
    loaded_killer_and_pepe_data,
):
    killer, pepe = loaded_killer_and_pepe_data

    killer_only = queries.dashboard_filter_options([killer.brand_id])
    pepe_only = queries.dashboard_filter_options([pepe.brand_id])
    combined = queries.dashboard_filter_options([killer.brand_id, pepe.brand_id])

    assert set(combined["categories"]) >= set(killer_only["categories"])
    assert set(combined["categories"]) >= set(pepe_only["categories"])
    combined_stores = {s["store_code"] for s in combined["stores"]}
    assert combined_stores >= {s["store_code"] for s in killer_only["stores"]}
    assert combined_stores >= {s["store_code"] for s in pepe_only["stores"]}


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
