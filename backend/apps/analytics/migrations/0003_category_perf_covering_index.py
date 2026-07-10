"""Day 11 load test finding: category_perf_top10's GROUP BY (category,
sub_category) over mv_category_perf -- the MV with the finest grain of the
three, since it includes store_id -- measured at 152ms for the real Killer
brand and 500-580ms for a synthetic 300-store/12M-row brand, both over the
~150ms target. EXPLAIN ANALYZE showed a plain Index Scan on the existing
(brand_id, category, sub_category, gender, store_id, ...) unique index,
which still needs a heap fetch per matching row (819k buffer hits + 55k
disk reads for the 1.58M-row synthetic case).

A covering index -- same leading columns, but INCLUDE-ing the four SUM'd
measure columns -- lets Postgres satisfy the whole query from the index
alone (an Index Only Scan), skipping heap access entirely. Verified: real
Killer 152ms -> 11.5ms (13x); synthetic 300-store brands ~570ms -> 143-
219ms (~3x). Doesn't fully close the gap for the most extreme synthetic
shape (300 stores/brand, well beyond any real brand in this dataset), but
that remaining cost is proportional to genuinely scanning/summing a large
row set, not a missing index -- a coarser rollup MV would be the next
lever if a real brand ever approaches that store count, not warranted now.

CREATE INDEX CONCURRENTLY (not a plain CREATE INDEX) so this is safe to
apply against a live table with real traffic, matching this codebase's
existing REFRESH MATERIALIZED VIEW CONCURRENTLY discipline -- requires
atomic=False, since CONCURRENTLY can't run inside a transaction block.
"""

from django.db import migrations

CREATE_SQL = """
CREATE INDEX CONCURRENTLY IF NOT EXISTS mv_category_perf_brand_cat_covering
    ON mv_category_perf (brand_id, category, sub_category)
    INCLUDE (mrp_value, net_value, discount_value, quantity);
"""

DROP_SQL = """
DROP INDEX CONCURRENTLY IF EXISTS mv_category_perf_brand_cat_covering;
"""


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("analytics", "0002_extend_materialized_views"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
