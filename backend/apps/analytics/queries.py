"""Analytics read-path: raw SQL over the materialized views only -- never
scans fact_sales directly (plan.md Day 7). Every function accepts already-
validated filter values; callers (views.py) own request-param parsing.
"""

from django.db import connection

from .filters import build_where

# Allowlists, never string-interpolated from raw user input -- prevents SQL
# injection via a dynamic ORDER BY/column, which parameterized queries
# can't cover (you can't bind a column name as a query parameter).
STORE_ORDER_COLUMNS = {
    "net": "net_value",
    "mrp": "mrp_value",
    "quantity": "quantity",
    "discount_pct": "discount_pct",
}
CATEGORY_ORDER_COLUMNS = STORE_ORDER_COLUMNS
METRIC_COLUMNS = {"net": "net_value", "mrp": "mrp_value", "quantity": "quantity"}
TREND_DIMENSIONS = {"financial_year", "month", "season"}


def _dictfetchall(cursor) -> list[dict]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def dashboard_summary(brand_id: int, filters: dict = None) -> dict:
    """Total/MRP/Net sales + total discount, broken down by financial year
    (client feedback: year is the chart baseline, not season). Queries
    mv_category_perf -- the same view category_perf_top10 uses -- rather
    than a coarser (brand x FY x month x season)-only view, since the
    dashboard is also filterable by category/sub_category/store, which
    only a view with that grain can answer; summing all the way up to just
    financial_year here still yields correct brand-wide totals."""
    where_sql, where_params = build_where("mv_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        SELECT
            financial_year,
            SUM(mrp_value) AS mrp_value,
            SUM(net_value) AS net_value,
            SUM(discount_value) AS discount_value,
            SUM(quantity) AS quantity
        FROM mv_category_perf
        WHERE brand_id = %(brand_id)s {extra_where}
        GROUP BY financial_year
        ORDER BY financial_year NULLS LAST
    """
    params = {"brand_id": brand_id, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        by_year = _dictfetchall(cursor)

    total = {
        "mrp_value": sum((row["mrp_value"] or 0) for row in by_year),
        "net_value": sum((row["net_value"] or 0) for row in by_year),
        "discount_value": sum((row["discount_value"] or 0) for row in by_year),
        "quantity": sum((row["quantity"] or 0) for row in by_year),
    }
    return {"total": total, "by_year": by_year}


def dashboard_filter_options(brand_id: int) -> dict:
    """Distinct values actually present in this brand's data, for
    populating the Dashboard's filter dropdowns -- never a static list, so
    a dropdown never offers a year/category/store with zero data behind
    it. Same source view as dashboard_summary itself."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_category_perf "
            "WHERE brand_id = %s ORDER BY financial_year",
            [brand_id],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT category FROM mv_category_perf "
            "WHERE brand_id = %s AND category IS NOT NULL ORDER BY category",
            [brand_id],
        )
        categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT sub_category FROM mv_category_perf "
            "WHERE brand_id = %s AND sub_category IS NOT NULL ORDER BY sub_category",
            [brand_id],
        )
        sub_categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_code, store_name FROM mv_category_perf "
            "WHERE brand_id = %s ORDER BY store_name",
            [brand_id],
        )
        stores = [{"store_code": row[0], "store_name": row[1]} for row in cursor.fetchall()]

    return {
        "financial_years": financial_years,
        "categories": categories,
        "sub_categories": sub_categories,
        "stores": stores,
    }


def store_perf_top10(brand_id: int, filters: dict = None, order_by: str = "net") -> list[dict]:
    order_column = STORE_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("mv_store_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                store_id, store_code, store_name, city, zone,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_store_perf
            WHERE brand_id = %(brand_id)s {extra_where}
            GROUP BY store_id, store_code, store_name, city, zone
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
        LIMIT 10
    """
    params = {"brand_id": brand_id, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def category_perf_top10(brand_id: int, filters: dict = None, order_by: str = "net") -> list[dict]:
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("mv_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                category, sub_category,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_category_perf
            WHERE brand_id = %(brand_id)s {extra_where}
            GROUP BY category, sub_category
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
        LIMIT 10
    """
    params = {"brand_id": brand_id, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def _trend(mv_name: str, brand_id: int, dimension: str, metric: str, filters: dict) -> list[dict]:
    """Shared implementation for store_trend/category_trend: same three
    dimension choices, same metric choices, same MV-agnostic filter engine
    -- only the target MV and its supported filters differ per caller.

    Season ordering is data-driven (earliest calendar_year*12+month_no seen
    for that season_code) rather than parsed from the season *text*, which
    is deliberately untouched free-form brand vocabulary (SS23, "FASHION
    BASICS", CORE, ...) with no guaranteed lexical order.
    """
    if dimension not in TREND_DIMENSIONS:
        raise ValueError(f"unknown trend dimension: {dimension!r}")
    metric_column = METRIC_COLUMNS.get(metric, "net_value")
    where_sql, where_params = build_where(mv_name, filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    params = {"brand_id": brand_id, **where_params}

    if dimension == "financial_year":
        sql = f"""
            SELECT financial_year AS label, SUM({metric_column}) AS value
            FROM {mv_name}
            WHERE brand_id = %(brand_id)s {extra_where}
            GROUP BY financial_year
            ORDER BY financial_year
        """
    elif dimension == "month":
        sql = f"""
            SELECT financial_year, month_no, month_name,
                   MIN(calendar_year) AS calendar_year,
                   SUM({metric_column}) AS value
            FROM {mv_name}
            WHERE brand_id = %(brand_id)s {extra_where}
            GROUP BY financial_year, month_no, month_name
            ORDER BY MIN(calendar_year), month_no
        """
    else:  # season
        sql = f"""
            SELECT season_code AS label, SUM({metric_column}) AS value
            FROM {mv_name}
            WHERE brand_id = %(brand_id)s {extra_where}
            GROUP BY season_code
            ORDER BY MIN(calendar_year * 12 + month_no) NULLS LAST
        """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _dictfetchall(cursor)

    if dimension == "month":
        for row in rows:
            row["label"] = f"{row['month_name']} {row['calendar_year']}"
    return rows


def store_trend(brand_id: int, dimension: str, metric: str, store_code: str = None) -> list[dict]:
    """A store's (or, with no store_code, the whole brand's) performance
    over time. dimension: 'financial_year' (YoY) | 'month' (MoM) |
    'season' (Season-by-Season)."""
    return _trend("mv_store_perf", brand_id, dimension, metric, {"store": store_code})


def category_trend(
    brand_id: int,
    dimension: str,
    metric: str,
    category: str = None,
    sub_category: str = None,
    store_codes: list = None,
) -> list[dict]:
    """A category's (optionally sub_category's) performance over time,
    optionally scoped to one or more stores."""
    filters = {"category": category, "sub_category": sub_category, "store": store_codes}
    return _trend("mv_category_perf", brand_id, dimension, metric, filters)
