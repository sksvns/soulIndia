"""Client feedback on the Dashboard UI (see docs/plan.md): baseline the
chart on financial year, not season, and let the dashboard filter by
category/sub_category/store too -- none of which mv_sales_summary can
answer, since it was deliberately built at (brand x FY x month x season)
grain only, with no store/category dimension at all (see
apps/analytics/filters.py's MV_COLUMNS docstring). apps.analytics.queries.
dashboard_summary now queries mv_category_perf instead, which already has
every column needed (it's the same view category_perf_top10 uses).

That makes mv_sales_summary entirely unused -- dropping it isn't just
cleanup, it removes one of the three views refresh_all() rebuilds on
every single upload, for zero benefit after this change (see
docs/load-test.md's corrected Phase 2 scaling note on why every
unnecessary MV refresh directly costs upload latency, not just an async
background cost).
"""

from django.db import migrations

DROP_SQL = "DROP MATERIALIZED VIEW IF EXISTS mv_sales_summary;"

REVERSE_SQL = """
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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0003_category_perf_covering_index"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP_SQL, reverse_sql=REVERSE_SQL),
    ]
