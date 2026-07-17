from datetime import date
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

    # Dashboard's store filter matches by store_name, not store_code (client
    # feedback: the same physical store gets a different code per brand, so
    # name is the identity that should combine across brands).
    one_store = queries.dashboard_summary([brand.brand_id], {"store": "SILVER SQUARE - PATNA"})
    assert one_store["total"]["net_value"] == Decimal("500.00")  # row 505 only


@pytest.mark.django_db
def test_dashboard_filter_options_reflects_real_data_only(loaded_trend_data):
    brand = loaded_trend_data

    options = queries.dashboard_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]
    assert set(options["categories"]) == {"SHIRTS", "JEANS"}
    assert set(options["stores"]) == {"AADARSH ENTERPRISES - DUMRAO", "SILVER SQUARE - PATNA"}


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
    assert set(combined["stores"]) >= set(killer_only["stores"])
    assert set(combined["stores"]) >= set(pepe_only["stores"])


@pytest.fixture
def loaded_killer_and_pepe_same_store_name(loaded_killer_data, data_inserter_user):
    """Pepe data at a store sharing Killer's store *name* but under a
    different store_code -- the exact cross-brand scenario the client
    described: one store, one code per brand, but the same real-world
    store name."""
    from apps.ingestion.models import UploadBatch

    pepe = DimBrand.objects.get(brand_code="PEPE")
    pepe_config = BrandUploadConfig.objects.get(brand=pepe)
    same_name_row = {
        **PEPE_GOOD_ROWS[0],
        "Store Name": "AADARSH ENTERPRISES - DUMRAO",
        "STORE CODE": "PEPE-DUMRAO-01",
        "BillNo": "PEPE-SHARED-001",
    }
    batch = UploadBatch.objects.create(
        brand=pepe,
        config=pepe_config,
        uploaded_by=data_inserter_user,
        file_name="pepe_shared_store.xlsx",
        object_key="uploads/pepe/menswear/pepe_shared_store.xlsx",
    )
    result = run_pipeline(
        pepe, pepe_config, pepe_workbook([same_name_row]), "pepe_shared_store.xlsx"
    )
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return loaded_killer_data, pepe


@pytest.mark.django_db
def test_dashboard_combines_same_store_name_across_brands_when_all_brands_selected(
    loaded_killer_and_pepe_same_store_name,
):
    """The actual client ask: on the all-brands dashboard, a store name
    that exists under a different store_code per brand should combine
    every brand's data for it, not just whichever brand owns that one
    store_code."""
    killer, pepe = loaded_killer_and_pepe_same_store_name

    combined = queries.dashboard_summary(
        [killer.brand_id, pepe.brand_id], {"store": "AADARSH ENTERPRISES - DUMRAO"}
    )
    # Killer's 3 rows at ESIS170/"AADARSH ENTERPRISES - DUMRAO" (EXPECTED_TOTAL_NET)
    # plus Pepe's 1 row at its own differently-coded same-named store.
    assert combined["total"]["net_value"] == EXPECTED_TOTAL_NET + Decimal("1799.00")

    options = queries.dashboard_filter_options([killer.brand_id, pepe.brand_id])
    assert (
        options["stores"].count("AADARSH ENTERPRISES - DUMRAO") == 1
    )  # deduped, not one per brand


@pytest.mark.django_db
def test_store_perf_orders_by_requested_column(loaded_killer_data):
    brand = loaded_killer_data

    rows, total_count = queries.store_perf([brand.brand_id], order_by="net")
    assert total_count == 1  # all 3 rows are the same single store, ESIS170
    assert len(rows) == 1
    assert rows[0]["store_code"] == "ESIS170"
    assert rows[0]["net_value"] == EXPECTED_TOTAL_NET
    assert rows[0]["mrp_value"] == EXPECTED_TOTAL_MRP
    assert rows[0]["discount_pct"] is not None


def _many_store_rows(n):
    """n distinct stores, one row each, ascending net_value -- purely
    synthetic data for exercising pagination (client feedback: sorting +
    paging over the complete result, not just one loaded page)."""
    return [
        {
            **KILLER_GOOD_ROWS[0],
            "BILL NO \nINVOICE NO": 900 + i,
            "STORE CODE": f"PGSTORE{i:02d}",
            "NAME": f"PAGINATION STORE {i:02d}",
            "MRP": 1000 + i * 100,
            "QTY \nSALE": 1,
            "NET \nSALE \nVALUE": 1000 + i * 100,
            "DISCOUNT \nVALUE": 0,
            "MRP \nSALE \nVALUE": 1000 + i * 100,
        }
        for i in range(1, n + 1)
    ]


@pytest.fixture
def loaded_many_stores_data(killer_brand_and_config, data_inserter_user):
    from apps.ingestion.models import UploadBatch

    brand, config = killer_brand_and_config
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="many_stores.xlsx",
        object_key="uploads/killer/menswear/many_stores.xlsx",
    )
    result = run_pipeline(brand, config, killer_workbook(_many_store_rows(15)), "many_stores.xlsx")
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return brand


@pytest.mark.django_db
def test_store_perf_pages_over_the_full_sorted_result_not_just_one_page(
    loaded_many_stores_data,
):
    """15 stores, each a distinct net_value -- proves paging happens over
    the whole ORDER-BY'd result: page 2 continues the same descending
    ranking, it doesn't independently re-sort just its own 5 rows."""
    brand = loaded_many_stores_data

    page1, total = queries.store_perf([brand.brand_id], order_by="net", limit=10, offset=0)
    assert total == 15
    assert len(page1) == 10
    assert [r["net_value"] for r in page1] == sorted((r["net_value"] for r in page1), reverse=True)
    assert page1[0]["net_value"] == Decimal("2500.00")  # highest, i=15
    assert page1[-1]["net_value"] == Decimal("1600.00")  # 10th highest, i=6

    page2, total2 = queries.store_perf([brand.brand_id], order_by="net", limit=10, offset=10)
    assert total2 == 15
    assert len(page2) == 5
    assert page2[0]["net_value"] == Decimal("1500.00")  # i=5, ranking continues from page 1
    assert page2[-1]["net_value"] == Decimal("1100.00")  # i=1, lowest overall

    all_rows, total3 = queries.store_perf([brand.brand_id], order_by="net", limit=None, offset=0)
    assert total3 == 15
    assert len(all_rows) == 15


@pytest.mark.django_db
def test_store_perf_total_count_correct_even_when_page_is_out_of_range(
    loaded_many_stores_data,
):
    """Requesting a page past the last row must still report the true
    total_count, not 0 -- an out-of-range page has no rows to read a
    COUNT(*) OVER() window value from, so total_count has to come from a
    genuinely separate query."""
    brand = loaded_many_stores_data

    rows, total = queries.store_perf([brand.brand_id], order_by="net", limit=10, offset=100)
    assert rows == []
    assert total == 15


@pytest.mark.django_db
def test_store_perf_combines_every_brand_when_no_single_brand_requested(
    loaded_killer_and_pepe_data,
):
    """Client feedback: the Stores page's default view is every active
    brand combined too, same as the Dashboard."""
    killer, pepe = loaded_killer_and_pepe_data

    killer_only, killer_total = queries.store_perf([killer.brand_id], limit=None)
    pepe_only, pepe_total = queries.store_perf([pepe.brand_id], limit=None)
    combined, combined_total = queries.store_perf([killer.brand_id, pepe.brand_id], limit=None)

    assert combined_total == killer_total + pepe_total
    assert len(combined) == len(killer_only) + len(pepe_only)


@pytest.mark.django_db
def test_store_filter_options_reflects_real_data_only(loaded_trend_data):
    brand = loaded_trend_data

    options = queries.store_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]


@pytest.mark.django_db
def test_category_ranking_reflects_every_category_and_store_filter(loaded_killer_data):
    """category_ranking groups by category only (client feedback: the
    Categories page's line chart is top-level-category only), is never
    capped at a top-N, and filters store by name -- not code -- since
    brand is optional here too (same convention as the Dashboard)."""
    brand = loaded_killer_data

    results = queries.category_ranking([brand.brand_id], order_by="net")
    categories = {row["category"] for row in results}
    assert categories == {"SHIRTS", "JEANS"}

    filtered = queries.category_ranking(
        [brand.brand_id], {"store": ["AADARSH ENTERPRISES - DUMRAO"]}
    )
    assert len(filtered) == 2  # SHIRTS and JEANS, same store

    no_match = queries.category_ranking([brand.brand_id], {"store": ["NOSUCHSTORE"]})
    assert no_match == []


@pytest.mark.django_db
def test_category_filter_options_reflects_real_data_only(loaded_trend_data):
    brand = loaded_trend_data

    options = queries.category_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]
    assert options["stores"] == ["AADARSH ENTERPRISES - DUMRAO", "SILVER SQUARE - PATNA"]


@pytest.mark.django_db
def test_category_line_chart_switches_granularity_same_as_dashboard(loaded_trend_data):
    """Same year/month/week adaptation as dashboard_summary, just once per
    requested category. Also proves zero-fill: JEANS has no FY24-25 data
    at all, but still gets a 0-valued slot there rather than a shorter
    breakdown array that would misalign the two lines' x-axes."""
    brand = loaded_trend_data

    result = queries.category_line_chart([brand.brand_id], {}, ["SHIRTS", "JEANS"])

    assert result["granularity"] == "year"
    by_category = {
        s["category"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]
    }
    assert set(by_category) == {"SHIRTS", "JEANS"}
    assert list(by_category["SHIRTS"]) == ["23-24", "24-25"]
    assert by_category["SHIRTS"]["23-24"]["net_value"] == Decimal("3300.00")  # rows 501+502+505
    assert by_category["SHIRTS"]["24-25"]["net_value"] == Decimal("3000.00")  # row 504
    assert by_category["JEANS"]["23-24"]["net_value"] == Decimal("1500.00")  # row 503
    assert by_category["JEANS"]["24-25"]["net_value"] == 0  # zero-filled, JEANS has no 24-25 rows
    assert by_category["JEANS"]["24-25"]["discount_pct"] is None


@pytest.mark.django_db
def test_category_line_chart_monthly_when_only_year_selected(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.category_line_chart(
        [brand.brand_id], {"financial_year": "23-24"}, ["SHIRTS", "JEANS"]
    )

    assert result["granularity"] == "month"
    by_category = {
        s["category"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]
    }
    assert list(by_category["SHIRTS"]) == ["April", "July", "October"]  # canonical, fiscal order
    assert by_category["SHIRTS"]["April"]["net_value"] == Decimal("1500.00")  # rows 501+505
    assert by_category["SHIRTS"]["July"]["net_value"] == Decimal("1800.00")  # row 502
    assert by_category["SHIRTS"]["October"]["net_value"] == 0  # zero-filled
    assert by_category["JEANS"]["October"]["net_value"] == Decimal("1500.00")  # row 503
    assert by_category["JEANS"]["April"]["net_value"] == 0  # zero-filled


@pytest.mark.django_db
def test_category_line_chart_weekly_when_year_and_month_selected(loaded_killer_data):
    """KILLER_GOOD_ROWS' 3 rows land in 3 different ISO weeks of April
    2023 -- Apr 5 (SHIRTS), Apr 15 (SHIRTS return), Apr 26 (JEANS) -- so
    this also proves per-category zero-fill at week grain."""
    brand = loaded_killer_data

    result = queries.category_line_chart(
        [brand.brand_id], {"financial_year": "23-24", "month": 4}, ["SHIRTS", "JEANS"]
    )

    assert result["granularity"] == "week"
    by_category = {
        s["category"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]
    }
    assert list(by_category["SHIRTS"]) == ["Week 1", "Week 2", "Week 3"]
    assert by_category["SHIRTS"]["Week 1"]["net_value"] == Decimal("2124.00")  # Apr 5
    assert by_category["SHIRTS"]["Week 2"]["net_value"] == Decimal("-1519.00")  # Apr 15 return
    assert by_category["SHIRTS"]["Week 3"]["net_value"] == 0  # zero-filled, JEANS' week
    assert by_category["JEANS"]["Week 3"]["net_value"] == Decimal("2450.00")  # Apr 26
    assert by_category["JEANS"]["Week 1"]["net_value"] == 0  # zero-filled


@pytest.mark.django_db
def test_category_line_chart_empty_categories_returns_empty_series(loaded_killer_data):
    brand = loaded_killer_data

    result = queries.category_line_chart([brand.brand_id], {}, [])

    assert result["series"] == []


@pytest.mark.django_db
def test_subcategory_ranking_reflects_every_subcategory_and_store_filter(loaded_killer_data):
    """Killer's column_map maps sub_category from the same source data
    category/sub_category coincidentally share in these fixtures, but
    this still exercises subcategory_ranking's own grouping/SQL path
    independently of category_ranking's."""
    brand = loaded_killer_data

    results = queries.subcategory_ranking([brand.brand_id], order_by="net")
    subcategories = {row["sub_category"] for row in results}
    assert subcategories == {"SHIRTS", "JEANS"}

    filtered = queries.subcategory_ranking(
        [brand.brand_id], {"store": ["AADARSH ENTERPRISES - DUMRAO"]}
    )
    assert len(filtered) == 2

    no_match = queries.subcategory_ranking([brand.brand_id], {"store": ["NOSUCHSTORE"]})
    assert no_match == []


@pytest.mark.django_db
def test_subcategory_filter_options_reflects_real_data_only(loaded_trend_data):
    brand = loaded_trend_data

    options = queries.subcategory_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]
    assert options["stores"] == ["AADARSH ENTERPRISES - DUMRAO", "SILVER SQUARE - PATNA"]


@pytest.mark.django_db
def test_subcategory_line_chart_switches_granularity_with_zero_fill(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.subcategory_line_chart([brand.brand_id], {}, ["SHIRTS", "JEANS"])

    assert result["granularity"] == "year"
    by_subcategory = {
        s["sub_category"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]
    }
    assert by_subcategory["SHIRTS"]["23-24"]["net_value"] == Decimal("3300.00")
    assert by_subcategory["JEANS"]["24-25"]["net_value"] == 0  # zero-filled


@pytest.fixture
def loaded_color_trend_data(killer_brand_and_config, data_inserter_user):
    """Two colors with different financial-year coverage -- neither
    KILLER_GOOD_ROWS nor KILLER_TREND_ROWS vary color/size at all (every
    row inherits PINK/L from its base row), so this is a dedicated
    fixture for color/size line-chart granularity + zero-fill testing,
    mirroring loaded_trend_data's category shape but on SHADE/SIZE."""
    from apps.ingestion.models import UploadBatch

    brand, config = killer_brand_and_config
    rows = [
        {
            **KILLER_GOOD_ROWS[0],
            "BILL NO \nINVOICE NO": 701,
            "NEW DATE": date(2023, 4, 5),
            "MONTH": "APRIL",
            "F. YEAR": "23-24",
            "SHADE": "RED",
            "SIZE": "M",
            "MRP": 1000,
            "QTY \nSALE": 1,
            "NET \nSALE \nVALUE": 1000,
            "DISCOUNT \nVALUE": 0,
            "MRP \nSALE \nVALUE": 1000,
        },
        {
            **KILLER_GOOD_ROWS[0],
            "BILL NO \nINVOICE NO": 702,
            "NEW DATE": date(2023, 7, 10),
            "MONTH": "JULY",
            "F. YEAR": "23-24",
            "SHADE": "RED",
            "SIZE": "M",
            "MRP": 2000,
            "QTY \nSALE": 1,
            "NET \nSALE \nVALUE": 1800,
            "DISCOUNT \nVALUE": 200,
            "MRP \nSALE \nVALUE": 2000,
        },
        {
            **KILLER_GOOD_ROWS[0],
            "BILL NO \nINVOICE NO": 703,
            "NEW DATE": date(2023, 10, 15),
            "MONTH": "OCTOBER",
            "F. YEAR": "23-24",
            # Distinct barcode: dim_product resolves color/size/category
            # once per barcode, first-row-wins (dimension_resolver.py) --
            # reusing the base row's barcode here would silently keep
            # RED/M for this row too.
            "NEW EAN CODE": 9999999999901,
            "SHADE": "BLUE",
            "SIZE": "L",
            "MRP": 750,
            "QTY \nSALE": 2,
            "NET \nSALE \nVALUE": 1500,
            "DISCOUNT \nVALUE": 0,
            "MRP \nSALE \nVALUE": 1500,
        },
        {
            **KILLER_GOOD_ROWS[0],
            "BILL NO \nINVOICE NO": 704,
            "NEW DATE": date(2024, 4, 20),
            "MONTH": "APRIL",
            "F. YEAR": "24-25",
            "SHADE": "RED",
            "SIZE": "M",
            "MRP": 3000,
            "QTY \nSALE": 1,
            "NET \nSALE \nVALUE": 3000,
            "DISCOUNT \nVALUE": 0,
            "MRP \nSALE \nVALUE": 3000,
        },
    ]
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="color_trend.xlsx",
        object_key="uploads/killer/menswear/color_trend.xlsx",
    )
    result = run_pipeline(brand, config, killer_workbook(rows), "color_trend.xlsx")
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return brand


@pytest.mark.django_db
def test_color_ranking_reflects_every_color_and_category_filter(loaded_color_trend_data):
    brand = loaded_color_trend_data

    results = queries.color_ranking([brand.brand_id], order_by="net")
    colors = {row["color"] for row in results}
    assert colors == {"RED", "BLUE"}

    # All rows here are SHIRTS (base row's MAIN CATEGORY, never overridden).
    filtered = queries.color_ranking([brand.brand_id], {"category": "SHIRTS"})
    assert {row["color"] for row in filtered} == {"RED", "BLUE"}

    no_match = queries.color_ranking([brand.brand_id], {"category": "NOSUCHCATEGORY"})
    assert no_match == []


@pytest.mark.django_db
def test_color_filter_options_reflects_real_data_only(loaded_color_trend_data):
    brand = loaded_color_trend_data

    options = queries.color_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]
    assert options["categories"] == ["SHIRTS"]
    assert options["stores"] == ["AADARSH ENTERPRISES - DUMRAO"]


@pytest.mark.django_db
def test_color_line_chart_switches_granularity_with_zero_fill(loaded_color_trend_data):
    brand = loaded_color_trend_data

    result = queries.color_line_chart([brand.brand_id], {}, ["RED", "BLUE"])

    assert result["granularity"] == "year"
    by_color = {s["color"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]}
    assert list(by_color["RED"]) == ["23-24", "24-25"]
    assert by_color["RED"]["23-24"]["net_value"] == Decimal("2800.00")  # 1000 + 1800
    assert by_color["RED"]["24-25"]["net_value"] == Decimal("3000.00")
    assert by_color["BLUE"]["23-24"]["net_value"] == Decimal("1500.00")
    assert by_color["BLUE"]["24-25"]["net_value"] == 0  # zero-filled
    assert by_color["BLUE"]["24-25"]["discount_pct"] is None


@pytest.mark.django_db
def test_color_line_chart_monthly_when_only_year_selected(loaded_color_trend_data):
    brand = loaded_color_trend_data

    result = queries.color_line_chart(
        [brand.brand_id], {"financial_year": "23-24"}, ["RED", "BLUE"]
    )

    assert result["granularity"] == "month"
    by_color = {s["color"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]}
    assert list(by_color["RED"]) == ["April", "July", "October"]
    assert by_color["RED"]["April"]["net_value"] == Decimal("1000.00")
    assert by_color["RED"]["October"]["net_value"] == 0  # zero-filled
    assert by_color["BLUE"]["October"]["net_value"] == Decimal("1500.00")


@pytest.mark.django_db
def test_color_line_chart_weekly_when_year_and_month_selected(loaded_color_trend_data):
    brand = loaded_color_trend_data

    result = queries.color_line_chart(
        [brand.brand_id], {"financial_year": "23-24", "month": 4}, ["RED"]
    )

    assert result["granularity"] == "week"
    labels = [row["label"] for row in result["series"][0]["breakdown"]]
    assert labels == ["Week 1"]
    assert result["series"][0]["breakdown"][0]["net_value"] == Decimal("1000.00")


@pytest.mark.django_db
def test_size_ranking_reflects_every_size_and_category_filter(loaded_color_trend_data):
    brand = loaded_color_trend_data

    results = queries.size_ranking([brand.brand_id], order_by="net")
    sizes = {row["size"] for row in results}
    assert sizes == {"M", "L"}

    filtered = queries.size_ranking([brand.brand_id], {"category": "SHIRTS"})
    assert {row["size"] for row in filtered} == {"M", "L"}


@pytest.mark.django_db
def test_size_filter_options_reflects_real_data_only(loaded_color_trend_data):
    brand = loaded_color_trend_data

    options = queries.size_filter_options([brand.brand_id])

    assert options["financial_years"] == ["23-24", "24-25"]
    assert options["categories"] == ["SHIRTS"]


@pytest.mark.django_db
def test_size_line_chart_switches_granularity_with_zero_fill(loaded_color_trend_data):
    brand = loaded_color_trend_data

    result = queries.size_line_chart([brand.brand_id], {}, ["M", "L"])

    assert result["granularity"] == "year"
    by_size = {s["size"]: {row["label"]: row for row in s["breakdown"]} for s in result["series"]}
    assert by_size["M"]["23-24"]["net_value"] == Decimal("2800.00")
    assert by_size["L"]["24-25"]["net_value"] == 0  # zero-filled


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
