"""Client feedback: a fourth Category subsection, "Fit", same pattern as
Color/Size (migration 0005). `dim_product.fit` already exists and is
already in the attribute registry -- it was just never exposed as its own
ranking/chart page.

Feasibility checked against real data before building this: Killer (99%
of products), Junior Killer (99.9%), and Pepe (100%) all have real,
meaningful fit values. Kraus's real ongoing export format has no FIT
column at all (0/447 products) -- same situation as sub_category, which
Kraus also doesn't supply, and which the existing Subcategory page
already handles by simply not surfacing any groups for a brand with no
non-null values, not by breaking. `WHERE p.fit IS NOT NULL` below is the
same exclusion Color/Size already use, so Kraus's rows are silently
absent from mv_fit_perf rather than showing up as blank fits.

Grain, structure, and reasoning are identical to mv_color_perf/mv_size_perf
(see migration 0005's docstring) -- a third narrow, purpose-built view
rather than adding fit to mv_category_perf's grain.
"""

from django.db import migrations

DISCOUNT_PCT_CASE = """
    CASE WHEN mrp_value = 0 THEN NULL ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END
"""

CREATE_SQL = f"""
CREATE MATERIALIZED VIEW mv_fit_perf AS
SELECT
    brand_id,
    fit,
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
        p.fit,
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
    WHERE p.fit IS NOT NULL
    GROUP BY f.brand_id, p.fit, p.category, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name
) agg;

CREATE UNIQUE INDEX mv_fit_perf_uniq ON mv_fit_perf
    (brand_id, fit, category, store_id, financial_year, month_no);
"""

DROP_SQL = """
DROP MATERIALIZED VIEW IF EXISTS mv_fit_perf;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0005_create_color_size_materialized_views"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
