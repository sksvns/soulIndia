"""Analytics read-path: raw SQL over the materialized views only -- never
scans fact_sales directly (plan.md Day 7). Every function accepts already-
validated filter values; callers (views.py) own request-param parsing.
"""

from django.db import connection

# Allowlists, never string-interpolated from raw user input -- prevents SQL
# injection via a dynamic ORDER BY column, which parameterized queries can't
# cover (you can't bind a column name as a query parameter).
STORE_ORDER_COLUMNS = {
    "net": "net_value",
    "mrp": "mrp_value",
    "quantity": "quantity",
    "discount_pct": "discount_pct",
}
CATEGORY_ORDER_COLUMNS = STORE_ORDER_COLUMNS


def _dictfetchall(cursor) -> list[dict]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def dashboard_summary(brand_id: int, financial_year: str = None, month_no: int = None) -> dict:
    """Total/MRP/Net sales + total discount, broken down by season."""
    sql = """
        SELECT
            season_code,
            SUM(mrp_value) AS mrp_value,
            SUM(net_value) AS net_value,
            SUM(discount_value) AS discount_value,
            SUM(quantity) AS quantity
        FROM mv_sales_summary
        WHERE brand_id = %(brand_id)s
          AND (%(financial_year)s IS NULL OR financial_year = %(financial_year)s)
          AND (%(month_no)s IS NULL OR month_no = %(month_no)s)
        GROUP BY season_code
        ORDER BY season_code NULLS LAST
    """
    params = {"brand_id": brand_id, "financial_year": financial_year, "month_no": month_no}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        by_season = _dictfetchall(cursor)

    total = {
        "mrp_value": sum((row["mrp_value"] or 0) for row in by_season),
        "net_value": sum((row["net_value"] or 0) for row in by_season),
        "discount_value": sum((row["discount_value"] or 0) for row in by_season),
        "quantity": sum((row["quantity"] or 0) for row in by_season),
    }
    return {"total": total, "by_season": by_season}


def store_perf_top10(
    brand_id: int, financial_year: str = None, month_no: int = None, order_by: str = "net"
) -> list[dict]:
    order_column = STORE_ORDER_COLUMNS.get(order_by, "net_value")
    sql = f"""
        WITH agg AS (
            SELECT
                store_id, store_code, store_name,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_store_perf
            WHERE brand_id = %(brand_id)s
              AND (%(financial_year)s IS NULL OR financial_year = %(financial_year)s)
              AND (%(month_no)s IS NULL OR month_no = %(month_no)s)
            GROUP BY store_id, store_code, store_name
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
        LIMIT 10
    """
    params = {"brand_id": brand_id, "financial_year": financial_year, "month_no": month_no}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def category_perf_top10(
    brand_id: int,
    financial_year: str = None,
    month_no: int = None,
    store_ids: list[int] = None,
    order_by: str = "net",
) -> list[dict]:
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    sql = f"""
        WITH agg AS (
            SELECT
                category, sub_category,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_category_perf
            WHERE brand_id = %(brand_id)s
              AND (%(financial_year)s IS NULL OR financial_year = %(financial_year)s)
              AND (%(month_no)s IS NULL OR month_no = %(month_no)s)
              AND (%(store_ids)s IS NULL OR store_id = ANY(%(store_ids)s))
            GROUP BY category, sub_category
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
        LIMIT 10
    """
    params = {
        "brand_id": brand_id,
        "financial_year": financial_year,
        "month_no": month_no,
        "store_ids": store_ids,
    }
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)
