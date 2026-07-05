"""Creates the three Phase-1 aggregate materialized views (plan.md Sec 3).

Grouped by dim_calendar's *computed* financial_year/month_no/month_name/
quarter -- not the brand's raw supplied month/FY/quarter text (which lives
in fact_sales.extra for audit, per ADR captured in docs/schema.md). The
computed calendar values are consistent across every brand and never null,
which is what a shared aggregate/filter/trend layer needs; the frozen
"trust season/FY/month as supplied" rule governs the canonical attribute a
user is shown, not this internal aggregation grain -- the raw text stays
retrievable from fact_sales.extra for audit.

discount_pct is computed here, never stored on fact_sales (frozen rule).
discount_bucket precomputes discount% into ranges so Day 8's discount-range
filter can use a plain equality/IN condition instead of a functional one.

Every MV gets a unique index -- required for REFRESH MATERIALIZED VIEW
CONCURRENTLY (Day 6's loader calls this after every load; see
apps/analytics/materialized_views.py).
"""

from django.db import migrations

DISCOUNT_BUCKET_CASE = """
    CASE
        WHEN mrp_value = 0 THEN NULL
        WHEN 100 * (1 - net_value / mrp_value) < 0 THEN 'markup'
        WHEN 100 * (1 - net_value / mrp_value) < 10 THEN '0-10%'
        WHEN 100 * (1 - net_value / mrp_value) < 20 THEN '10-20%'
        WHEN 100 * (1 - net_value / mrp_value) < 30 THEN '20-30%'
        WHEN 100 * (1 - net_value / mrp_value) < 40 THEN '30-40%'
        WHEN 100 * (1 - net_value / mrp_value) < 50 THEN '40-50%'
        ELSE '50%+'
    END
"""

DISCOUNT_PCT_CASE = """
    CASE WHEN mrp_value = 0 THEN NULL ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END
"""

CREATE_SQL = f"""
CREATE MATERIALIZED VIEW mv_sales_summary AS
SELECT
    brand_id,
    financial_year,
    month_no,
    month_name,
    quarter,
    season_id,
    season_code,
    mrp_value,
    net_value,
    discount_value,
    quantity,
    row_count
FROM (
    SELECT
        f.brand_id,
        c.financial_year,
        c.month_no,
        c.month_name,
        c.quarter,
        f.season_id,
        s.season_code,
        SUM(f.mrp_value) AS mrp_value,
        SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value,
        SUM(f.quantity) AS quantity,
        COUNT(*) AS row_count
    FROM fact_sales f
    JOIN dim_calendar c ON c.date_id = f.date_id
    LEFT JOIN dim_season s ON s.season_id = f.season_id
    GROUP BY f.brand_id, c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code
) agg;

CREATE UNIQUE INDEX mv_sales_summary_uniq ON mv_sales_summary
    (brand_id, financial_year, month_no, season_id);


CREATE MATERIALIZED VIEW mv_store_perf AS
SELECT
    brand_id,
    store_id,
    store_code,
    store_name,
    financial_year,
    month_no,
    month_name,
    quarter,
    season_id,
    season_code,
    mrp_value,
    net_value,
    discount_value,
    quantity,
    row_count,
    {DISCOUNT_PCT_CASE} AS discount_pct,
    {DISCOUNT_BUCKET_CASE} AS discount_bucket
FROM (
    SELECT
        f.brand_id,
        f.store_id,
        st.store_code,
        st.store_name,
        c.financial_year,
        c.month_no,
        c.month_name,
        c.quarter,
        f.season_id,
        s.season_code,
        SUM(f.mrp_value) AS mrp_value,
        SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value,
        SUM(f.quantity) AS quantity,
        COUNT(*) AS row_count
    FROM fact_sales f
    JOIN dim_calendar c ON c.date_id = f.date_id
    JOIN dim_store st ON st.store_id = f.store_id
    LEFT JOIN dim_season s ON s.season_id = f.season_id
    GROUP BY f.brand_id, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code
) agg;

CREATE UNIQUE INDEX mv_store_perf_uniq ON mv_store_perf
    (brand_id, store_id, financial_year, month_no, season_id);


CREATE MATERIALIZED VIEW mv_category_perf AS
SELECT
    brand_id,
    category,
    sub_category,
    store_id,
    store_code,
    store_name,
    financial_year,
    month_no,
    month_name,
    quarter,
    season_id,
    season_code,
    mrp_value,
    net_value,
    discount_value,
    quantity,
    row_count,
    {DISCOUNT_PCT_CASE} AS discount_pct,
    {DISCOUNT_BUCKET_CASE} AS discount_bucket
FROM (
    SELECT
        f.brand_id,
        p.category,
        p.sub_category,
        f.store_id,
        st.store_code,
        st.store_name,
        c.financial_year,
        c.month_no,
        c.month_name,
        c.quarter,
        f.season_id,
        s.season_code,
        SUM(f.mrp_value) AS mrp_value,
        SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value,
        SUM(f.quantity) AS quantity,
        COUNT(*) AS row_count
    FROM fact_sales f
    JOIN dim_calendar c ON c.date_id = f.date_id
    JOIN dim_store st ON st.store_id = f.store_id
    JOIN dim_product p ON p.product_id = f.product_id
    LEFT JOIN dim_season s ON s.season_id = f.season_id
    GROUP BY f.brand_id, p.category, p.sub_category, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code
) agg;

CREATE UNIQUE INDEX mv_category_perf_uniq ON mv_category_perf
    (brand_id, category, sub_category, store_id, financial_year, month_no, season_id);
"""

DROP_SQL = """
DROP MATERIALIZED VIEW IF EXISTS mv_category_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_store_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_sales_summary;
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("ingestion", "0001_create_fact_sales"),
        ("masterdata", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
