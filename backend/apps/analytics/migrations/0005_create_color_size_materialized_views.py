"""Client feedback: new Color and Size pages (top-level ranking + a
multi-select line chart, same pattern as the Categories page). Neither
column exists in any materialized view -- migration 0002's docstring
deliberately left color/fit/size/article_code out of mv_category_perf
("much higher cardinality than gender... wiring them in is an additive
migration exactly like this one, not a redesign, if that need
materializes"). That need has now materialized.

Rather than adding color+size to mv_category_perf itself (which would
multiply its existing category/sub_category/gender/store grain by both
colors' and sizes' cardinality, for a capability only two new pages
need), these are two new, narrower, purpose-built views -- Dashboard/
Stores/Categories and their already-tuned covering index are completely
unaffected.

Grain is intentionally minimal: brand x color (or size) x category x
store x financial_year x month -- no season/gender/discount_bucket,
since the Color/Size pages don't filter by those. Stores are still kept
by store_id/store_code/store_name (not folded away) so the filter engine
can match by store_name across brands, same as mv_category_perf's
dashboard_category_perf variant -- these views are brand-optional/
all-combined from day one, so there's no separate store-by-code
consumer to keep backwards compatible with (unlike mv_category_perf,
which still has to serve Stores'/Trends' store-by-code filtering too).

Weekly-granularity breakdowns for Color/Size don't need either new view
at all -- they query fact_sales directly (same deliberate exception as
_dashboard_weekly_breakdown/_category_weekly_breakdown), since
dim_product already has color/size columns.
"""

from django.db import migrations

DISCOUNT_PCT_CASE = """
    CASE WHEN mrp_value = 0 THEN NULL ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END
"""

CREATE_SQL = f"""
CREATE MATERIALIZED VIEW mv_color_perf AS
SELECT
    brand_id,
    color,
    category,
    store_id,
    store_code,
    store_name,
    financial_year,
    calendar_year,
    month_no,
    month_name,
    mrp_value,
    net_value,
    discount_value,
    quantity,
    row_count,
    {DISCOUNT_PCT_CASE} AS discount_pct
FROM (
    SELECT
        f.brand_id,
        p.color,
        p.category,
        f.store_id,
        st.store_code,
        st.store_name,
        c.financial_year,
        EXTRACT(YEAR FROM MIN(f.sale_date))::smallint AS calendar_year,
        c.month_no,
        c.month_name,
        SUM(f.mrp_value) AS mrp_value,
        SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value,
        SUM(f.quantity) AS quantity,
        COUNT(*) AS row_count
    FROM fact_sales f
    JOIN dim_calendar c ON c.date_id = f.date_id
    JOIN dim_store st ON st.store_id = f.store_id
    JOIN dim_product p ON p.product_id = f.product_id
    WHERE p.color IS NOT NULL
    GROUP BY f.brand_id, p.color, p.category, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name
) agg;

CREATE UNIQUE INDEX mv_color_perf_uniq ON mv_color_perf
    (brand_id, color, category, store_id, financial_year, month_no);


CREATE MATERIALIZED VIEW mv_size_perf AS
SELECT
    brand_id,
    size,
    category,
    store_id,
    store_code,
    store_name,
    financial_year,
    calendar_year,
    month_no,
    month_name,
    mrp_value,
    net_value,
    discount_value,
    quantity,
    row_count,
    {DISCOUNT_PCT_CASE} AS discount_pct
FROM (
    SELECT
        f.brand_id,
        p.size,
        p.category,
        f.store_id,
        st.store_code,
        st.store_name,
        c.financial_year,
        EXTRACT(YEAR FROM MIN(f.sale_date))::smallint AS calendar_year,
        c.month_no,
        c.month_name,
        SUM(f.mrp_value) AS mrp_value,
        SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value,
        SUM(f.quantity) AS quantity,
        COUNT(*) AS row_count
    FROM fact_sales f
    JOIN dim_calendar c ON c.date_id = f.date_id
    JOIN dim_store st ON st.store_id = f.store_id
    JOIN dim_product p ON p.product_id = f.product_id
    WHERE p.size IS NOT NULL
    GROUP BY f.brand_id, p.size, p.category, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name
) agg;

CREATE UNIQUE INDEX mv_size_perf_uniq ON mv_size_perf
    (brand_id, size, category, store_id, financial_year, month_no);
"""

DROP_SQL = """
DROP MATERIALIZED VIEW IF EXISTS mv_size_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_color_perf;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0004_drop_unused_mv_sales_summary"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
