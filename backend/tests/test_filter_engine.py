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
