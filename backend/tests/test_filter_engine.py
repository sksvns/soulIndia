from apps.analytics.filters import build_where


def test_build_where_with_no_filters_returns_empty():
    sql, params = build_where("mv_store_perf", {})
    assert sql == ""
    assert params == {}


def test_build_where_with_none_or_empty_values_are_skipped():
    sql, params = build_where("mv_store_perf", {"city": None, "zone": "", "store": []})
    assert sql == ""
    assert params == {}


def test_build_where_maps_canonical_name_to_real_column():
    sql, params = build_where("mv_store_perf", {"city": "DUMRAO"})
    assert sql == "city = %(filter_city)s"
    assert params == {"filter_city": "DUMRAO"}


def test_build_where_combines_multiple_filters_with_and():
    sql, params = build_where("mv_store_perf", {"city": "DUMRAO", "zone": "EAST"})
    assert "city = %(filter_city)s" in sql
    assert "zone = %(filter_zone)s" in sql
    assert " AND " in sql
    assert params == {"filter_city": "DUMRAO", "filter_zone": "EAST"}


def test_build_where_list_value_becomes_any_clause():
    sql, params = build_where("mv_category_perf", {"store": ["ESIS170", "ESIS999"]})
    assert sql == "store_code = ANY(%(filter_store)s)"
    assert params == {"filter_store": ["ESIS170", "ESIS999"]}


def test_build_where_silently_drops_filters_the_target_mv_does_not_support():
    """mv_store_perf has no category/sub_category grain -- asking it to
    filter by category is a no-op, not an error, since different MVs
    legitimately support different filter subsets by design."""
    sql, params = build_where("mv_store_perf", {"category": "SHIRTS", "financial_year": "23-24"})
    assert "category" not in sql
    assert sql == "financial_year = %(filter_financial_year)s"
    assert params == {"filter_financial_year": "23-24"}


def test_build_where_unknown_mv_name_supports_no_filters():
    sql, params = build_where("mv_does_not_exist", {"city": "DUMRAO"})
    assert sql == ""
    assert params == {}


def test_discount_range_maps_to_discount_bucket_column():
    sql, params = build_where("mv_store_perf", {"discount_range": "10-20%"})
    assert sql == "discount_bucket = %(filter_discount_range)s"
    assert params == {"filter_discount_range": "10-20%"}


def test_gender_only_supported_on_category_perf_not_store_perf():
    sql_store, _ = build_where("mv_store_perf", {"gender": "MENS"})
    sql_category, _ = build_where("mv_category_perf", {"gender": "MENS"})
    assert sql_store == ""
    assert sql_category == "gender = %(filter_gender)s"


def test_dashboard_category_perf_filters_store_by_name_not_code():
    """The Dashboard's own breakdown queries filter store by name (client
    feedback: the same physical store has a different store_code per
    brand), unlike every other mv_category_perf-backed page."""
    sql, params = build_where("dashboard_category_perf", {"store": "AADARSH ENTERPRISES - DUMRAO"})
    assert sql == "store_name = %(filter_store)s"
    assert params == {"filter_store": "AADARSH ENTERPRISES - DUMRAO"}


def test_fact_sales_filters_store_by_name_and_ignores_financial_year_month():
    """financial_year/month are deliberately absent from this entry --
    _dashboard_weekly_breakdown pins them via dim_calendar directly, not
    through this generic filter engine."""
    sql, params = build_where(
        "fact_sales",
        {"store": "AADARSH ENTERPRISES - DUMRAO", "financial_year": "23-24", "month": 4},
    )
    assert sql == "st.store_name = %(filter_store)s"
    assert params == {"filter_store": "AADARSH ENTERPRISES - DUMRAO"}
