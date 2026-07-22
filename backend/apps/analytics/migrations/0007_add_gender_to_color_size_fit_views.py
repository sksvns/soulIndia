"""Client feedback: a Gender filter on the Color/Size/Fit pages (Category
and Sub-Category already support it -- they share mv_category_perf, which
has always had gender in its grain since migration 0002).

mv_color_perf/mv_size_perf/mv_fit_perf don't have gender at all, so this
adds it to each view's grain -- can't ALTER a materialized view to add a
joined column, so this drops and recreates all three, same idiom as
migrations 0005/0006.

Real-data check before building this: gender is genuinely sparse --
only Pepe supplies it (100% of its products); Killer, Junior Killer, and
Kraus have none at all. Same situation Kraus is already in for
sub_category/fit -- a brand without the dimension just contributes no
rows for it, not an error. `WHERE p.gender IS NOT NULL` is not added
here (unlike color/size/fit's own `WHERE p.<dim> IS NOT NULL`): gender
is a *filter*, not this view's own grouping dimension, so a NULL gender
still needs its own row (folded into `GROUP BY ... p.gender`, which
already treats NULL as one distinct group in SQL) so non-Pepe brands'
color/size/fit data doesn't just disappear from these views.

The unique index must now include gender: real data has genuine
per-gender splits of the same (brand, color/size/fit, category, store,
FY, month) combination (Pepe sells both MENS and LADIES within the same
store/category/month), so gender is part of the natural key now, not
just an additional filterable column.
"""

from django.db import migrations

DISCOUNT_PCT_CASE = """
    CASE WHEN mrp_value = 0 THEN NULL ELSE ROUND(100 * (1 - net_value / mrp_value), 2) END
"""


def _view_sql(dimension_column: str, view_name: str) -> str:
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
SELECT
    brand_id,
    {dimension_column},
    category,
    gender,
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
        p.{dimension_column},
        p.category,
        p.gender,
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
    WHERE p.{dimension_column} IS NOT NULL
    GROUP BY f.brand_id, p.{dimension_column}, p.category, p.gender, f.store_id,
             st.store_code, st.store_name, c.financial_year, c.month_no, c.month_name
) agg;

CREATE UNIQUE INDEX {view_name}_uniq ON {view_name}
    (brand_id, {dimension_column}, category, store_id, financial_year, month_no, gender);
"""


def _old_view_sql(dimension_column: str, view_name: str) -> str:
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
SELECT
    brand_id,
    {dimension_column},
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
        p.{dimension_column},
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
    WHERE p.{dimension_column} IS NOT NULL
    GROUP BY f.brand_id, p.{dimension_column}, p.category, f.store_id, st.store_code, st.store_name,
             c.financial_year, c.month_no, c.month_name
) agg;

CREATE UNIQUE INDEX {view_name}_uniq ON {view_name}
    (brand_id, {dimension_column}, category, store_id, financial_year, month_no);
"""


DROP_SQL = """
DROP MATERIALIZED VIEW IF EXISTS mv_fit_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_size_perf;
DROP MATERIALIZED VIEW IF EXISTS mv_color_perf;
"""

CREATE_SQL = (
    DROP_SQL
    + _view_sql("color", "mv_color_perf")
    + _view_sql("size", "mv_size_perf")
    + _view_sql("fit", "mv_fit_perf")
)

REVERSE_SQL = (
    DROP_SQL
    + _old_view_sql("color", "mv_color_perf")
    + _old_view_sql("size", "mv_size_perf")
    + _old_view_sql("fit", "mv_fit_perf")
)


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0006_create_fit_materialized_view"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=REVERSE_SQL),
    ]
