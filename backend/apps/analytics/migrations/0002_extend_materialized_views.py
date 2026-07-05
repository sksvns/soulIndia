"""Extends the three Day 7 materialized views for Day 8's filter engine and
trends API. Postgres has no "ALTER MATERIALIZED VIEW ... ADD COLUMN" --
extending an MV means dropping and recreating it, which is why this
migration reproduces the full Day 7 definitions rather than just the diff.

Additions:
- `city`, `zone` on mv_store_perf -- functionally dependent on store_id
  (same store always has the same city/zone), so free: no new GROUP BY
  granularity, no row-count change, just two more columns to filter on.
- `gender` on mv_category_perf -- genuinely a new grouping dimension (a
  category can span multiple genders within one store/month), so this
  *does* add rows, but gender's cardinality is low (a handful of values,
  and it's the frozen "optional dimension" -- only some brands supply it).
- `calendar_year` on all three -- computed from MIN(sale_date), not by
  parsing the brand's supplied financial_year text. Needed for correct
  chronological Month-over-Month ordering across financial years (Apr is
  month_no 4 but the *first* month of an FY, so ordering by month_no alone
  within a single FY is right, but comparing across FYs needs a real
  calendar year, and the supplied financial_year is free text like "23-24"
  -- deliberately not something to string-parse in SQL when the real
  sale_date is sitting right there in the same aggregation).

Deliberately NOT added: color/fit/size/article_code. These are product-
instance-level attributes (much higher cardinality than gender) that no
Phase 1 view (dashboard, store-wise, category-wise, or these trends) groups
or filters by -- adding them now would inflate every MV for a capability
nothing yet uses. attribute_registry still lists them as filterable
attributes for a future view; wiring them in is an additive migration
exactly like this one, not a redesign, if that need materializes.
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

DROP_SQL = """
DROP MATERIALIZED VIEW IF EXISTS mv_category_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_store_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_sales_summary;
"""

CREATE_SQL = f"""
CREATE MATERIALIZED VIEW mv_sales_summary AS
SELECT
    brand_id,
    financial_year,
    calendar_year,
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
        EXTRACT(YEAR FROM MIN(f.sale_date))::smallint AS calendar_year,
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
    city,
    zone,
    financial_year,
    calendar_year,
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
        st.city,
        st.zone,
        c.financial_year,
        EXTRACT(YEAR FROM MIN(f.sale_date))::smallint AS calendar_year,
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
    GROUP BY f.brand_id, f.store_id, st.store_code, st.store_name, st.city, st.zone,
             c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code
) agg;

CREATE UNIQUE INDEX mv_store_perf_uniq ON mv_store_perf
    (brand_id, store_id, financial_year, month_no, season_id);


CREATE MATERIALIZED VIEW mv_category_perf AS
SELECT
    brand_id,
    category,
    sub_category,
    gender,
    store_id,
    store_code,
    store_name,
    financial_year,
    calendar_year,
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
        p.gender,
        f.store_id,
        st.store_code,
        st.store_name,
        c.financial_year,
        EXTRACT(YEAR FROM MIN(f.sale_date))::smallint AS calendar_year,
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
    GROUP BY f.brand_id, p.category, p.sub_category, p.gender, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code
) agg;

CREATE UNIQUE INDEX mv_category_perf_uniq ON mv_category_perf
    (brand_id, category, sub_category, gender, store_id, financial_year, month_no, season_id);
"""

# Reverse: recreate the original Day 7 (narrower) definitions, so migrating
# backward restores the previous state rather than leaving the MVs dropped.
REVERSE_CREATE_SQL = f"""
CREATE MATERIALIZED VIEW mv_sales_summary AS
SELECT
    brand_id, financial_year, month_no, month_name, quarter, season_id, season_code,
    mrp_value, net_value, discount_value, quantity, row_count
FROM (
    SELECT
        f.brand_id, c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code,
        SUM(f.mrp_value) AS mrp_value, SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value, SUM(f.quantity) AS quantity, COUNT(*) AS row_count
    FROM fact_sales f
    JOIN dim_calendar c ON c.date_id = f.date_id
    LEFT JOIN dim_season s ON s.season_id = f.season_id
    GROUP BY f.brand_id, c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code
) agg;
CREATE UNIQUE INDEX mv_sales_summary_uniq ON mv_sales_summary
    (brand_id, financial_year, month_no, season_id);

CREATE MATERIALIZED VIEW mv_store_perf AS
SELECT
    brand_id, store_id, store_code, store_name, financial_year, month_no, month_name, quarter,
    season_id, season_code, mrp_value, net_value, discount_value, quantity, row_count,
    {DISCOUNT_PCT_CASE} AS discount_pct, {DISCOUNT_BUCKET_CASE} AS discount_bucket
FROM (
    SELECT
        f.brand_id, f.store_id, st.store_code, st.store_name, c.financial_year, c.month_no,
        c.month_name, c.quarter, f.season_id, s.season_code,
        SUM(f.mrp_value) AS mrp_value, SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value, SUM(f.quantity) AS quantity, COUNT(*) AS row_count
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
    brand_id, category, sub_category, store_id, store_code, store_name, financial_year, month_no,
    month_name, quarter, season_id, season_code, mrp_value, net_value, discount_value, quantity,
    row_count, {DISCOUNT_PCT_CASE} AS discount_pct, {DISCOUNT_BUCKET_CASE} AS discount_bucket
FROM (
    SELECT
        f.brand_id, p.category, p.sub_category, f.store_id, st.store_code, st.store_name,
        c.financial_year, c.month_no, c.month_name, c.quarter, f.season_id, s.season_code,
        SUM(f.mrp_value) AS mrp_value, SUM(f.net_value) AS net_value,
        SUM(f.discount_value) AS discount_value, SUM(f.quantity) AS quantity, COUNT(*) AS row_count
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


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0001_create_materialized_views"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP_SQL + CREATE_SQL, reverse_sql=DROP_SQL + REVERSE_CREATE_SQL),
    ]
