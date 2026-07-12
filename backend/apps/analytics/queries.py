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


def dashboard_summary(brand_ids: list[int], filters: dict = None) -> dict:
    """Total/MRP/Net sales + total discount, broken down at whichever
    granularity the current filter selection can meaningfully chart
    (client feedback): year by default, month once a single year is
    picked, week once that year is narrowed to a single month too --
    each level answering "what does the level below the one I just
    picked look like", never a separate report type to choose.

    brand_ids is always a list -- a single selected brand passes a
    one-element list, "all brands" (client feedback: the dashboard's
    default view) passes every active brand's id, so every branch below
    is one query path either way (brand_id = ANY(...)), not a
    conditional branch."""
    filters = filters or {}
    financial_year = filters.get("financial_year")
    month = filters.get("month")

    if financial_year and month:
        granularity = "week"
        breakdown = _dashboard_weekly_breakdown(brand_ids, financial_year, month, filters)
    elif financial_year:
        granularity = "month"
        breakdown = _dashboard_monthly_breakdown(brand_ids, filters)
    else:
        granularity = "year"
        breakdown = _dashboard_yearly_breakdown(brand_ids, filters)

    total = {
        "mrp_value": sum((row["mrp_value"] or 0) for row in breakdown),
        "net_value": sum((row["net_value"] or 0) for row in breakdown),
        "discount_value": sum((row["discount_value"] or 0) for row in breakdown),
        "quantity": sum((row["quantity"] or 0) for row in breakdown),
    }
    return {"total": total, "breakdown": breakdown, "granularity": granularity}


def _dashboard_yearly_breakdown(brand_ids: list[int], filters: dict) -> list[dict]:
    """Queries mv_category_perf -- the same view category_perf_top10 uses --
    rather than a coarser (brand x FY x month x season)-only view, since the
    dashboard is also filterable by category/sub_category/store, which
    only a view with that grain can answer; summing all the way up to just
    financial_year here still yields correct brand-wide totals."""
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        SELECT
            financial_year,
            SUM(mrp_value) AS mrp_value,
            SUM(net_value) AS net_value,
            SUM(discount_value) AS discount_value,
            SUM(quantity) AS quantity
        FROM mv_category_perf
        WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
        GROUP BY financial_year
        ORDER BY financial_year NULLS LAST
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("financial_year") or "Unknown"
    return rows


def _dashboard_monthly_breakdown(brand_ids: list[int], filters: dict) -> list[dict]:
    """A single financial_year's months -- filters already pins the year
    (build_where turns it into the same WHERE financial_year = ... clause
    dashboard_filter_options's dropdown relies on), so grouping by
    month_no/month_name here is a breakdown *within* that year, not
    across years. Ordered by calendar_year then month_no (not month_no
    alone) so April..March reads left-to-right, matching the fiscal
    year's actual month order."""
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        SELECT
            month_name,
            SUM(mrp_value) AS mrp_value,
            SUM(net_value) AS net_value,
            SUM(discount_value) AS discount_value,
            SUM(quantity) AS quantity
        FROM mv_category_perf
        WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
        GROUP BY month_no, month_name
        ORDER BY MIN(calendar_year), month_no
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("month_name")
    return rows


def _dashboard_weekly_breakdown(
    brand_ids: list[int], financial_year: str, month: int, filters: dict
) -> list[dict]:
    """A single financial_year + month's weeks. The one deliberate
    exception to "never scan fact_sales directly" (plan.md Day 7): no
    materialized view has day-level grain, and adding one at
    mv_category_perf's full (brand x category x sub_category x gender x
    store) dimensionality would multiply its row count by ~30 for a
    feature that only ever reads one brand-month at a time. fact_sales is
    LIST-partitioned by brand_id and BRIN-indexed on sale_date, so
    "one brand, one month" prunes to a single partition and a narrow
    date-range scan within it -- not a scan of the whole table's history.

    Weeks are ISO (Monday-start) via date_trunc, labeled by their
    chronological position within the month ("Week 1", "Week 2", ...)
    rather than the raw ISO week-of-year number, which wraps confusingly
    at year boundaries and means nothing to a store manager."""
    where_sql, where_params = build_where("fact_sales", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        SELECT
            date_trunc('week', f.sale_date)::date AS week_start,
            SUM(f.mrp_value) AS mrp_value,
            SUM(f.net_value) AS net_value,
            SUM(f.discount_value) AS discount_value,
            SUM(f.quantity) AS quantity
        FROM fact_sales f
        JOIN dim_calendar c ON c.date_id = f.date_id
        JOIN dim_product p ON p.product_id = f.product_id
        JOIN dim_store st ON st.store_id = f.store_id
        WHERE f.brand_id = ANY(%(brand_ids)s)
          AND c.financial_year = %(financial_year)s
          AND c.month_no = %(month_no)s
          {extra_where}
        GROUP BY week_start
        ORDER BY week_start
    """
    params = {
        "brand_ids": brand_ids,
        "financial_year": financial_year,
        "month_no": month,
        **where_params,
    }
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _dictfetchall(cursor)
    for i, row in enumerate(rows):
        row["label"] = f"Week {i + 1}"
        del row["week_start"]
    return rows


def dashboard_filter_options(brand_ids: list[int]) -> dict:
    """Distinct values actually present across brand_ids' data, for
    populating the Dashboard's filter dropdowns -- never a static list, so
    a dropdown never offers a year/category/store with zero data behind
    it. Same source view as dashboard_summary itself, same brand_ids-is-
    always-a-list convention (one brand or every active brand).

    Stores are listed by store_name, deduped across brand_ids, not by
    store_code: each brand assigns its own code to the same physical
    store, so "every active brand" would otherwise list e.g. "CHANDA MAMA
    - HAJIPUR" three times, once per brand's code for it (client
    feedback). dashboard_summary's store filter matches this same
    store_name-based identity (see filters.MV_COLUMNS'
    dashboard_category_perf/fact_sales entries), so picking one combines
    that store's data across every brand that has it."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT category FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND category IS NOT NULL ORDER BY category",
            [brand_ids],
        )
        categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT sub_category FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND sub_category IS NOT NULL ORDER BY sub_category",
            [brand_ids],
        )
        sub_categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_name FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND store_name IS NOT NULL ORDER BY store_name",
            [brand_ids],
        )
        stores = [row[0] for row in cursor.fetchall()]

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
