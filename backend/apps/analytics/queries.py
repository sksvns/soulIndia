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
    """Queries mv_category_perf -- the same view category_ranking uses --
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


def store_perf(
    brand_ids: list[int],
    filters: dict = None,
    order_by: str = "net",
    limit: int | None = 10,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Every store matching brand_ids/filters, ranked by order_by --
    sorted and paged entirely in SQL over the complete aggregated result
    (client feedback: sorting must apply to all the data, not just
    whichever page is currently loaded). limit=None returns every row
    unpaged (the "All" page-size choice).

    total_count is queried separately from the paged rows, not via a
    COUNT(*) OVER() window column on the same query: a window column only
    surfaces on rows the final LIMIT/OFFSET actually returns, so an
    out-of-range page (e.g. offset past the last row, or a filter that
    now matches fewer rows than before) would come back with zero rows
    and no way to read a correct total from them."""
    where_sql, where_params = build_where("mv_store_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    agg_sql = f"""
        SELECT
            store_id, store_code, store_name, city, zone,
            SUM(mrp_value) AS mrp_value,
            SUM(net_value) AS net_value,
            SUM(discount_value) AS discount_value,
            SUM(quantity) AS quantity
        FROM mv_store_perf
        WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
        GROUP BY store_id, store_code, store_name, city, zone
    """
    order_column = STORE_ORDER_COLUMNS.get(order_by, "net_value")
    limit_sql = "LIMIT %(limit)s OFFSET %(offset)s" if limit is not None else ""
    page_sql = f"""
        WITH agg AS ({agg_sql})
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
        {limit_sql}
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM ({agg_sql}) counted", params)
        total_count = cursor.fetchone()[0]

        cursor.execute(page_sql, {**params, "limit": limit, "offset": offset})
        rows = _dictfetchall(cursor)
    return rows, total_count


def store_filter_options(brand_ids: list[int]) -> dict:
    """Distinct financial years actually present, for the Stores page's
    own simplified filter bar's Year dropdown (client feedback: brand
    optional/all-combined by default, other filters as live dropdowns --
    same convention as the Dashboard's own filter bar)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_store_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]
    return {"financial_years": financial_years}


def category_ranking(
    brand_ids: list[int], filters: dict = None, order_by: str = "net"
) -> list[dict]:
    """Every category matching brand_ids/filters, ranked by order_by --
    never capped at a top-N: this feeds the Categories page's multi-select
    (every category must be choosable, not just the top few) as well as
    its top-5-by-net default selection. Categories are naturally a small,
    bounded set (unlike stores), so no pagination is needed here.

    Grouped by category only, not category+sub_category (client feedback:
    the Categories page's line chart operates at the top-level category;
    sub_category is no longer a dimension this page exposes).

    Uses the store-by-name filter engine (dashboard_category_perf), not
    store-by-code: brand is optional here too (client feedback -- every
    active brand combined by default, same as the Dashboard), and a
    store_code is only unique within one brand."""
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                category,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_category_perf
            WHERE brand_id = ANY(%(brand_ids)s) AND category IS NOT NULL {extra_where}
            GROUP BY category
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def category_filter_options(brand_ids: list[int]) -> dict:
    """Distinct financial years, store names, and genders actually present,
    for the Categories page's own filter bar (brand/year/month/store/gender
    -- client feedback, same convention as the Dashboard's). Stores are
    listed by name, deduped across brands, matching dashboard_filter_options.
    Gender is genuinely brand-dependent -- only Pepe supplies it today
    (Killer/Junior Killer/Kraus don't), so this list is often empty or
    single-brand, same situation Kraus is already in for sub_category/fit."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_name FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND store_name IS NOT NULL ORDER BY store_name",
            [brand_ids],
        )
        stores = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT gender FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND gender IS NOT NULL ORDER BY gender",
            [brand_ids],
        )
        genders = [row[0] for row in cursor.fetchall()]

    return {"financial_years": financial_years, "stores": stores, "genders": genders}


_ZERO_BREAKDOWN = {
    "mrp_value": 0,
    "net_value": 0,
    "discount_value": 0,
    "quantity": 0,
    "discount_pct": None,
}


def category_line_chart(brand_ids: list[int], filters: dict, categories: list[str]) -> dict:
    """Each requested category's own MRP/Net/Discount/Quantity broken down
    at whichever granularity the filter selection can chart (client
    feedback) -- the same year/month/week adaptation dashboard_summary
    uses, just once per category instead of once for the whole brand.

    Every category's breakdown shares one x-axis, built independently of
    which categories were requested (so it doesn't shift as the selection
    changes) and zero-filled for any category with no data in a given
    period, so multi-line charts stay aligned point-for-point."""
    if not categories:
        return {"granularity": "year", "series": []}

    filters = filters or {}
    financial_year = filters.get("financial_year")
    month = filters.get("month")

    if financial_year and month:
        granularity = "week"
        labels, rows = _category_weekly_breakdown(
            brand_ids, financial_year, month, filters, categories
        )
    elif financial_year:
        granularity = "month"
        labels, rows = _category_monthly_breakdown(brand_ids, filters, categories)
    else:
        granularity = "year"
        labels, rows = _category_yearly_breakdown(brand_ids, filters, categories)

    by_category = {cat: {} for cat in categories}
    for row in rows:
        by_category[row["category"]][row["label"]] = row

    series = [
        {
            "category": cat,
            "breakdown": [
                {
                    "label": label,
                    **{k: by_category[cat].get(label, _ZERO_BREAKDOWN)[k] for k in _ZERO_BREAKDOWN},
                }
                for label in labels
            ],
        }
        for cat in categories
    ]
    return {"granularity": granularity, "series": series}


def _category_yearly_breakdown(
    brand_ids: list[int], filters: dict, categories: list[str]
) -> tuple[list[str], list[dict]]:
    """canonical labels: every financial_year present brand-wide (not
    restricted to `categories`), so the x-axis doesn't depend on which
    categories are selected."""
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT financial_year FROM mv_category_perf
            WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
            ORDER BY financial_year NULLS LAST
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] or "Unknown" for row in cursor.fetchall()]

        cat_where_sql, cat_where_params = build_where(
            "dashboard_category_perf", {**filters, "category": categories}
        )
        cat_extra_where = f"AND {cat_where_sql}" if cat_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    category, financial_year,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_category_perf
                WHERE brand_id = ANY(%(brand_ids)s) {cat_extra_where}
                GROUP BY category, financial_year
            ) agg
            """,
            {"brand_ids": brand_ids, **cat_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("financial_year") or "Unknown"
    return labels, rows


def _category_monthly_breakdown(
    brand_ids: list[int], filters: dict, categories: list[str]
) -> tuple[list[str], list[dict]]:
    """A single financial_year's months (filters already pins the year).
    canonical labels: every month present brand-wide, fiscal-chronological
    order, independent of which categories are selected."""
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT month_name FROM (
                SELECT month_no, month_name, MIN(calendar_year) AS calendar_year
                FROM mv_category_perf
                WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
                GROUP BY month_no, month_name
            ) m
            ORDER BY calendar_year, month_no
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] for row in cursor.fetchall()]

        cat_where_sql, cat_where_params = build_where(
            "dashboard_category_perf", {**filters, "category": categories}
        )
        cat_extra_where = f"AND {cat_where_sql}" if cat_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    category, month_name,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_category_perf
                WHERE brand_id = ANY(%(brand_ids)s) {cat_extra_where}
                GROUP BY category, month_no, month_name
            ) agg
            """,
            {"brand_ids": brand_ids, **cat_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("month_name")
    return labels, rows


def _category_weekly_breakdown(
    brand_ids: list[int], financial_year: str, month: int, filters: dict, categories: list[str]
) -> tuple[list[str], list[dict]]:
    """A single financial_year + month's weeks, per category. Same
    fact_sales exception as _dashboard_weekly_breakdown (see its
    docstring) -- now also grouped by category. canonical labels: every
    week with brand-wide activity that month, independent of which
    categories are selected, so a category with a data-free week still
    gets a "Week N" slot with zero values rather than the line skipping
    straight past it (which would misalign every line's x-axis)."""
    where_sql, where_params = build_where("fact_sales", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    base_params = {"brand_ids": brand_ids, "financial_year": financial_year, "month_no": month}
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT date_trunc('week', f.sale_date)::date AS week_start
            FROM fact_sales f
            JOIN dim_calendar c ON c.date_id = f.date_id
            JOIN dim_product p ON p.product_id = f.product_id
            JOIN dim_store st ON st.store_id = f.store_id
            WHERE f.brand_id = ANY(%(brand_ids)s)
              AND c.financial_year = %(financial_year)s
              AND c.month_no = %(month_no)s
              {extra_where}
            ORDER BY week_start
            """,
            {**base_params, **where_params},
        )
        week_labels = {row[0]: f"Week {i + 1}" for i, row in enumerate(cursor.fetchall())}
        labels = list(week_labels.values())

        cat_where_sql, cat_where_params = build_where(
            "fact_sales", {**filters, "category": categories}
        )
        cat_extra_where = f"AND {cat_where_sql}" if cat_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    p.category,
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
                  {cat_extra_where}
                GROUP BY p.category, week_start
            ) agg
            """,
            {**base_params, **cat_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = week_labels[row.pop("week_start")]
    return labels, rows


def subcategory_ranking(
    brand_ids: list[int], filters: dict = None, order_by: str = "net"
) -> list[dict]:
    """Every sub_category matching brand_ids/filters, ranked by order_by --
    same shape and conventions as category_ranking (never capped, brand-
    optional/all-combined, store-by-name), just one level finer (client
    feedback: a dedicated Subcategory page)."""
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                sub_category,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_category_perf
            WHERE brand_id = ANY(%(brand_ids)s) AND sub_category IS NOT NULL {extra_where}
            GROUP BY sub_category
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def subcategory_filter_options(brand_ids: list[int]) -> dict:
    """Distinct financial years, store names, and genders, same convention
    as category_filter_options (client feedback: Subcategory keeps the
    exact same brand/year/month/store/gender filter set as Categories, no
    extra Category filter)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_name FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND store_name IS NOT NULL ORDER BY store_name",
            [brand_ids],
        )
        stores = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT gender FROM mv_category_perf "
            "WHERE brand_id = ANY(%s) AND gender IS NOT NULL ORDER BY gender",
            [brand_ids],
        )
        genders = [row[0] for row in cursor.fetchall()]

    return {"financial_years": financial_years, "stores": stores, "genders": genders}


def subcategory_line_chart(brand_ids: list[int], filters: dict, subcategories: list[str]) -> dict:
    """Same adaptive year/month/week granularity and zero-fill guarantees
    as category_line_chart (see its docstring), grouped by sub_category."""
    if not subcategories:
        return {"granularity": "year", "series": []}

    filters = filters or {}
    financial_year = filters.get("financial_year")
    month = filters.get("month")

    if financial_year and month:
        granularity = "week"
        labels, rows = _subcategory_weekly_breakdown(
            brand_ids, financial_year, month, filters, subcategories
        )
    elif financial_year:
        granularity = "month"
        labels, rows = _subcategory_monthly_breakdown(brand_ids, filters, subcategories)
    else:
        granularity = "year"
        labels, rows = _subcategory_yearly_breakdown(brand_ids, filters, subcategories)

    by_subcategory = {sc: {} for sc in subcategories}
    for row in rows:
        by_subcategory[row["sub_category"]][row["label"]] = row

    series = [
        {
            "sub_category": sc,
            "breakdown": [
                {
                    "label": label,
                    **{
                        k: by_subcategory[sc].get(label, _ZERO_BREAKDOWN)[k]
                        for k in _ZERO_BREAKDOWN
                    },
                }
                for label in labels
            ],
        }
        for sc in subcategories
    ]
    return {"granularity": granularity, "series": series}


def _subcategory_yearly_breakdown(
    brand_ids: list[int], filters: dict, subcategories: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT financial_year FROM mv_category_perf
            WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
            ORDER BY financial_year NULLS LAST
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] or "Unknown" for row in cursor.fetchall()]

        sub_where_sql, sub_where_params = build_where(
            "dashboard_category_perf", {**filters, "sub_category": subcategories}
        )
        sub_extra_where = f"AND {sub_where_sql}" if sub_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    sub_category, financial_year,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_category_perf
                WHERE brand_id = ANY(%(brand_ids)s) {sub_extra_where}
                GROUP BY sub_category, financial_year
            ) agg
            """,
            {"brand_ids": brand_ids, **sub_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("financial_year") or "Unknown"
    return labels, rows


def _subcategory_monthly_breakdown(
    brand_ids: list[int], filters: dict, subcategories: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("dashboard_category_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT month_name FROM (
                SELECT month_no, month_name, MIN(calendar_year) AS calendar_year
                FROM mv_category_perf
                WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
                GROUP BY month_no, month_name
            ) m
            ORDER BY calendar_year, month_no
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] for row in cursor.fetchall()]

        sub_where_sql, sub_where_params = build_where(
            "dashboard_category_perf", {**filters, "sub_category": subcategories}
        )
        sub_extra_where = f"AND {sub_where_sql}" if sub_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    sub_category, month_name,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_category_perf
                WHERE brand_id = ANY(%(brand_ids)s) {sub_extra_where}
                GROUP BY sub_category, month_no, month_name
            ) agg
            """,
            {"brand_ids": brand_ids, **sub_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("month_name")
    return labels, rows


def _subcategory_weekly_breakdown(
    brand_ids: list[int], financial_year: str, month: int, filters: dict, subcategories: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("fact_sales", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    base_params = {"brand_ids": brand_ids, "financial_year": financial_year, "month_no": month}
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT date_trunc('week', f.sale_date)::date AS week_start
            FROM fact_sales f
            JOIN dim_calendar c ON c.date_id = f.date_id
            JOIN dim_product p ON p.product_id = f.product_id
            JOIN dim_store st ON st.store_id = f.store_id
            WHERE f.brand_id = ANY(%(brand_ids)s)
              AND c.financial_year = %(financial_year)s
              AND c.month_no = %(month_no)s
              {extra_where}
            ORDER BY week_start
            """,
            {**base_params, **where_params},
        )
        week_labels = {row[0]: f"Week {i + 1}" for i, row in enumerate(cursor.fetchall())}
        labels = list(week_labels.values())

        sub_where_sql, sub_where_params = build_where(
            "fact_sales", {**filters, "sub_category": subcategories}
        )
        sub_extra_where = f"AND {sub_where_sql}" if sub_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    p.sub_category,
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
                  {sub_extra_where}
                GROUP BY p.sub_category, week_start
            ) agg
            """,
            {**base_params, **sub_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = week_labels[row.pop("week_start")]
    return labels, rows


def color_ranking(brand_ids: list[int], filters: dict = None, order_by: str = "net") -> list[dict]:
    """Every color matching brand_ids/filters (optionally narrowed to one
    category via the Colors page's own Category filter), ranked by
    order_by -- feeds the multi-select (top 5 by net becomes the
    default), same conventions as category_ranking."""
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("mv_color_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                color,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_color_perf
            WHERE brand_id = ANY(%(brand_ids)s) AND color IS NOT NULL {extra_where}
            GROUP BY color
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def color_filter_options(brand_ids: list[int]) -> dict:
    """Distinct financial years/store names/categories, for the Colors
    page's filter bar (brand/year/month/store, plus a Category filter
    that defaults to every category combined -- client feedback, same
    "all, or narrow to one" convention as brand)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_color_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_name FROM mv_color_perf "
            "WHERE brand_id = ANY(%s) AND store_name IS NOT NULL ORDER BY store_name",
            [brand_ids],
        )
        stores = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT category FROM mv_color_perf "
            "WHERE brand_id = ANY(%s) AND category IS NOT NULL ORDER BY category",
            [brand_ids],
        )
        categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT gender FROM mv_color_perf "
            "WHERE brand_id = ANY(%s) AND gender IS NOT NULL ORDER BY gender",
            [brand_ids],
        )
        genders = [row[0] for row in cursor.fetchall()]

    return {
        "financial_years": financial_years,
        "stores": stores,
        "categories": categories,
        "genders": genders,
    }


def color_line_chart(brand_ids: list[int], filters: dict, colors: list[str]) -> dict:
    """Same adaptive year/month/week granularity and zero-fill guarantees
    as category_line_chart (see its docstring), grouped by color. filters
    may include "category" to narrow the whole chart to one category,
    same as any other filter here."""
    if not colors:
        return {"granularity": "year", "series": []}

    filters = filters or {}
    financial_year = filters.get("financial_year")
    month = filters.get("month")

    if financial_year and month:
        granularity = "week"
        labels, rows = _color_weekly_breakdown(brand_ids, financial_year, month, filters, colors)
    elif financial_year:
        granularity = "month"
        labels, rows = _color_monthly_breakdown(brand_ids, filters, colors)
    else:
        granularity = "year"
        labels, rows = _color_yearly_breakdown(brand_ids, filters, colors)

    by_color = {c: {} for c in colors}
    for row in rows:
        by_color[row["color"]][row["label"]] = row

    series = [
        {
            "color": c,
            "breakdown": [
                {
                    "label": label,
                    **{k: by_color[c].get(label, _ZERO_BREAKDOWN)[k] for k in _ZERO_BREAKDOWN},
                }
                for label in labels
            ],
        }
        for c in colors
    ]
    return {"granularity": granularity, "series": series}


def _color_yearly_breakdown(
    brand_ids: list[int], filters: dict, colors: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("mv_color_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT financial_year FROM mv_color_perf
            WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
            ORDER BY financial_year NULLS LAST
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] or "Unknown" for row in cursor.fetchall()]

        c_where_sql, c_where_params = build_where("mv_color_perf", {**filters, "color": colors})
        c_extra_where = f"AND {c_where_sql}" if c_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    color, financial_year,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_color_perf
                WHERE brand_id = ANY(%(brand_ids)s) {c_extra_where}
                GROUP BY color, financial_year
            ) agg
            """,
            {"brand_ids": brand_ids, **c_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("financial_year") or "Unknown"
    return labels, rows


def _color_monthly_breakdown(
    brand_ids: list[int], filters: dict, colors: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("mv_color_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT month_name FROM (
                SELECT month_no, month_name, MIN(calendar_year) AS calendar_year
                FROM mv_color_perf
                WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
                GROUP BY month_no, month_name
            ) m
            ORDER BY calendar_year, month_no
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] for row in cursor.fetchall()]

        c_where_sql, c_where_params = build_where("mv_color_perf", {**filters, "color": colors})
        c_extra_where = f"AND {c_where_sql}" if c_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    color, month_name,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_color_perf
                WHERE brand_id = ANY(%(brand_ids)s) {c_extra_where}
                GROUP BY color, month_no, month_name
            ) agg
            """,
            {"brand_ids": brand_ids, **c_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("month_name")
    return labels, rows


def _color_weekly_breakdown(
    brand_ids: list[int], financial_year: str, month: int, filters: dict, colors: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("fact_sales", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    base_params = {"brand_ids": brand_ids, "financial_year": financial_year, "month_no": month}
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT date_trunc('week', f.sale_date)::date AS week_start
            FROM fact_sales f
            JOIN dim_calendar c ON c.date_id = f.date_id
            JOIN dim_product p ON p.product_id = f.product_id
            JOIN dim_store st ON st.store_id = f.store_id
            WHERE f.brand_id = ANY(%(brand_ids)s)
              AND c.financial_year = %(financial_year)s
              AND c.month_no = %(month_no)s
              {extra_where}
            ORDER BY week_start
            """,
            {**base_params, **where_params},
        )
        week_labels = {row[0]: f"Week {i + 1}" for i, row in enumerate(cursor.fetchall())}
        labels = list(week_labels.values())

        c_where_sql, c_where_params = build_where("fact_sales", {**filters, "color": colors})
        c_extra_where = f"AND {c_where_sql}" if c_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    p.color,
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
                  {c_extra_where}
                GROUP BY p.color, week_start
            ) agg
            """,
            {**base_params, **c_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = week_labels[row.pop("week_start")]
    return labels, rows


def size_ranking(brand_ids: list[int], filters: dict = None, order_by: str = "net") -> list[dict]:
    """Every size matching brand_ids/filters (optionally narrowed to one
    category), ranked by order_by -- same conventions as color_ranking."""
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("mv_size_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                size,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_size_perf
            WHERE brand_id = ANY(%(brand_ids)s) AND size IS NOT NULL {extra_where}
            GROUP BY size
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def size_filter_options(brand_ids: list[int]) -> dict:
    """Distinct financial years/store names/categories, for the Sizes
    page's filter bar -- same convention as color_filter_options."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_size_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_name FROM mv_size_perf "
            "WHERE brand_id = ANY(%s) AND store_name IS NOT NULL ORDER BY store_name",
            [brand_ids],
        )
        stores = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT category FROM mv_size_perf "
            "WHERE brand_id = ANY(%s) AND category IS NOT NULL ORDER BY category",
            [brand_ids],
        )
        categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT gender FROM mv_size_perf "
            "WHERE brand_id = ANY(%s) AND gender IS NOT NULL ORDER BY gender",
            [brand_ids],
        )
        genders = [row[0] for row in cursor.fetchall()]

    return {
        "financial_years": financial_years,
        "stores": stores,
        "categories": categories,
        "genders": genders,
    }


def size_line_chart(brand_ids: list[int], filters: dict, sizes: list[str]) -> dict:
    """Same adaptive year/month/week granularity and zero-fill guarantees
    as color_line_chart, grouped by size."""
    if not sizes:
        return {"granularity": "year", "series": []}

    filters = filters or {}
    financial_year = filters.get("financial_year")
    month = filters.get("month")

    if financial_year and month:
        granularity = "week"
        labels, rows = _size_weekly_breakdown(brand_ids, financial_year, month, filters, sizes)
    elif financial_year:
        granularity = "month"
        labels, rows = _size_monthly_breakdown(brand_ids, filters, sizes)
    else:
        granularity = "year"
        labels, rows = _size_yearly_breakdown(brand_ids, filters, sizes)

    by_size = {sz: {} for sz in sizes}
    for row in rows:
        by_size[row["size"]][row["label"]] = row

    series = [
        {
            "size": sz,
            "breakdown": [
                {
                    "label": label,
                    **{k: by_size[sz].get(label, _ZERO_BREAKDOWN)[k] for k in _ZERO_BREAKDOWN},
                }
                for label in labels
            ],
        }
        for sz in sizes
    ]
    return {"granularity": granularity, "series": series}


def _size_yearly_breakdown(
    brand_ids: list[int], filters: dict, sizes: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("mv_size_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT financial_year FROM mv_size_perf
            WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
            ORDER BY financial_year NULLS LAST
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] or "Unknown" for row in cursor.fetchall()]

        s_where_sql, s_where_params = build_where("mv_size_perf", {**filters, "size": sizes})
        s_extra_where = f"AND {s_where_sql}" if s_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    size, financial_year,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_size_perf
                WHERE brand_id = ANY(%(brand_ids)s) {s_extra_where}
                GROUP BY size, financial_year
            ) agg
            """,
            {"brand_ids": brand_ids, **s_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("financial_year") or "Unknown"
    return labels, rows


def _size_monthly_breakdown(
    brand_ids: list[int], filters: dict, sizes: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("mv_size_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT month_name FROM (
                SELECT month_no, month_name, MIN(calendar_year) AS calendar_year
                FROM mv_size_perf
                WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
                GROUP BY month_no, month_name
            ) m
            ORDER BY calendar_year, month_no
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] for row in cursor.fetchall()]

        s_where_sql, s_where_params = build_where("mv_size_perf", {**filters, "size": sizes})
        s_extra_where = f"AND {s_where_sql}" if s_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    size, month_name,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_size_perf
                WHERE brand_id = ANY(%(brand_ids)s) {s_extra_where}
                GROUP BY size, month_no, month_name
            ) agg
            """,
            {"brand_ids": brand_ids, **s_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("month_name")
    return labels, rows


def _size_weekly_breakdown(
    brand_ids: list[int], financial_year: str, month: int, filters: dict, sizes: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("fact_sales", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    base_params = {"brand_ids": brand_ids, "financial_year": financial_year, "month_no": month}
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT date_trunc('week', f.sale_date)::date AS week_start
            FROM fact_sales f
            JOIN dim_calendar c ON c.date_id = f.date_id
            JOIN dim_product p ON p.product_id = f.product_id
            JOIN dim_store st ON st.store_id = f.store_id
            WHERE f.brand_id = ANY(%(brand_ids)s)
              AND c.financial_year = %(financial_year)s
              AND c.month_no = %(month_no)s
              {extra_where}
            ORDER BY week_start
            """,
            {**base_params, **where_params},
        )
        week_labels = {row[0]: f"Week {i + 1}" for i, row in enumerate(cursor.fetchall())}
        labels = list(week_labels.values())

        s_where_sql, s_where_params = build_where("fact_sales", {**filters, "size": sizes})
        s_extra_where = f"AND {s_where_sql}" if s_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    p.size,
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
                  {s_extra_where}
                GROUP BY p.size, week_start
            ) agg
            """,
            {**base_params, **s_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = week_labels[row.pop("week_start")]
    return labels, rows


def fit_ranking(brand_ids: list[int], filters: dict = None, order_by: str = "net") -> list[dict]:
    """Every fit matching brand_ids/filters (optionally narrowed to one
    category), ranked by order_by -- same conventions as color_ranking/
    size_ranking. Kraus contributes nothing here (no FIT column in its
    real export, mv_fit_perf excludes null-fit rows at refresh time), same
    as it already contributes nothing to Subcategory."""
    order_column = CATEGORY_ORDER_COLUMNS.get(order_by, "net_value")
    where_sql, where_params = build_where("mv_fit_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    sql = f"""
        WITH agg AS (
            SELECT
                fit,
                SUM(mrp_value) AS mrp_value,
                SUM(net_value) AS net_value,
                SUM(discount_value) AS discount_value,
                SUM(quantity) AS quantity
            FROM mv_fit_perf
            WHERE brand_id = ANY(%(brand_ids)s) AND fit IS NOT NULL {extra_where}
            GROUP BY fit
        )
        SELECT *,
            CASE WHEN mrp_value = 0 THEN NULL
                 ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
        FROM agg
        ORDER BY {order_column} DESC NULLS LAST
    """
    params = {"brand_ids": brand_ids, **where_params}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _dictfetchall(cursor)


def fit_filter_options(brand_ids: list[int]) -> dict:
    """Distinct financial years/store names/categories, for the Fit
    page's filter bar -- same convention as color_filter_options."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT financial_year FROM mv_fit_perf "
            "WHERE brand_id = ANY(%s) ORDER BY financial_year",
            [brand_ids],
        )
        financial_years = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT store_name FROM mv_fit_perf "
            "WHERE brand_id = ANY(%s) AND store_name IS NOT NULL ORDER BY store_name",
            [brand_ids],
        )
        stores = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT category FROM mv_fit_perf "
            "WHERE brand_id = ANY(%s) AND category IS NOT NULL ORDER BY category",
            [brand_ids],
        )
        categories = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT gender FROM mv_fit_perf "
            "WHERE brand_id = ANY(%s) AND gender IS NOT NULL ORDER BY gender",
            [brand_ids],
        )
        genders = [row[0] for row in cursor.fetchall()]

    return {
        "financial_years": financial_years,
        "stores": stores,
        "categories": categories,
        "genders": genders,
    }


def fit_line_chart(brand_ids: list[int], filters: dict, fits: list[str]) -> dict:
    """Same adaptive year/month/week granularity and zero-fill guarantees
    as color_line_chart, grouped by fit."""
    if not fits:
        return {"granularity": "year", "series": []}

    filters = filters or {}
    financial_year = filters.get("financial_year")
    month = filters.get("month")

    if financial_year and month:
        granularity = "week"
        labels, rows = _fit_weekly_breakdown(brand_ids, financial_year, month, filters, fits)
    elif financial_year:
        granularity = "month"
        labels, rows = _fit_monthly_breakdown(brand_ids, filters, fits)
    else:
        granularity = "year"
        labels, rows = _fit_yearly_breakdown(brand_ids, filters, fits)

    by_fit = {ft: {} for ft in fits}
    for row in rows:
        by_fit[row["fit"]][row["label"]] = row

    series = [
        {
            "fit": ft,
            "breakdown": [
                {
                    "label": label,
                    **{k: by_fit[ft].get(label, _ZERO_BREAKDOWN)[k] for k in _ZERO_BREAKDOWN},
                }
                for label in labels
            ],
        }
        for ft in fits
    ]
    return {"granularity": granularity, "series": series}


def _fit_yearly_breakdown(
    brand_ids: list[int], filters: dict, fits: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("mv_fit_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT financial_year FROM mv_fit_perf
            WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
            ORDER BY financial_year NULLS LAST
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] or "Unknown" for row in cursor.fetchall()]

        f_where_sql, f_where_params = build_where("mv_fit_perf", {**filters, "fit": fits})
        f_extra_where = f"AND {f_where_sql}" if f_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    fit, financial_year,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_fit_perf
                WHERE brand_id = ANY(%(brand_ids)s) {f_extra_where}
                GROUP BY fit, financial_year
            ) agg
            """,
            {"brand_ids": brand_ids, **f_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("financial_year") or "Unknown"
    return labels, rows


def _fit_monthly_breakdown(
    brand_ids: list[int], filters: dict, fits: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("mv_fit_perf", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT month_name FROM (
                SELECT month_no, month_name, MIN(calendar_year) AS calendar_year
                FROM mv_fit_perf
                WHERE brand_id = ANY(%(brand_ids)s) {extra_where}
                GROUP BY month_no, month_name
            ) m
            ORDER BY calendar_year, month_no
            """,
            {"brand_ids": brand_ids, **where_params},
        )
        labels = [row[0] for row in cursor.fetchall()]

        f_where_sql, f_where_params = build_where("mv_fit_perf", {**filters, "fit": fits})
        f_extra_where = f"AND {f_where_sql}" if f_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    fit, month_name,
                    SUM(mrp_value) AS mrp_value, SUM(net_value) AS net_value,
                    SUM(discount_value) AS discount_value, SUM(quantity) AS quantity
                FROM mv_fit_perf
                WHERE brand_id = ANY(%(brand_ids)s) {f_extra_where}
                GROUP BY fit, month_no, month_name
            ) agg
            """,
            {"brand_ids": brand_ids, **f_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = row.pop("month_name")
    return labels, rows


def _fit_weekly_breakdown(
    brand_ids: list[int], financial_year: str, month: int, filters: dict, fits: list[str]
) -> tuple[list[str], list[dict]]:
    where_sql, where_params = build_where("fact_sales", filters)
    extra_where = f"AND {where_sql}" if where_sql else ""
    base_params = {"brand_ids": brand_ids, "financial_year": financial_year, "month_no": month}
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT date_trunc('week', f.sale_date)::date AS week_start
            FROM fact_sales f
            JOIN dim_calendar c ON c.date_id = f.date_id
            JOIN dim_product p ON p.product_id = f.product_id
            JOIN dim_store st ON st.store_id = f.store_id
            WHERE f.brand_id = ANY(%(brand_ids)s)
              AND c.financial_year = %(financial_year)s
              AND c.month_no = %(month_no)s
              {extra_where}
            ORDER BY week_start
            """,
            {**base_params, **where_params},
        )
        week_labels = {row[0]: f"Week {i + 1}" for i, row in enumerate(cursor.fetchall())}
        labels = list(week_labels.values())

        f_where_sql, f_where_params = build_where("fact_sales", {**filters, "fit": fits})
        f_extra_where = f"AND {f_where_sql}" if f_where_sql else ""
        cursor.execute(
            f"""
            SELECT *,
                CASE WHEN mrp_value = 0 THEN NULL
                     ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END AS discount_pct
            FROM (
                SELECT
                    p.fit,
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
                  {f_extra_where}
                GROUP BY p.fit, week_start
            ) agg
            """,
            {**base_params, **f_where_params},
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row["label"] = week_labels[row.pop("week_start")]
    return labels, rows


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
