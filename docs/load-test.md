# Day 11 load test — methodology, scale, and results

Goal: prove the analytics read-path holds up at realistic Phase-1 scale
(~30–40M rows), find the actual bottleneck (not a guessed one), and fix it
with a measured, reproducible change. This is a query/MV/cache-performance
exercise, not a re-test of ingestion correctness — that's already covered
by Day 5/6's real-file validation tests.

## Data generation

`python manage.py generate_load_test_data --brand-code=LOADTEST_XXX ...`
(`backend/apps/ingestion/management/commands/generate_load_test_data.py`)
generates synthetic `fact_sales` rows via numpy-vectorized random
generation and a direct `COPY ... FROM STDIN` into Postgres, bypassing the
Excel-parse/per-row-validate pipeline entirely. Safety: the command
refuses any `--brand-code` that doesn't start with `LOADTEST`, so it can
never touch real brand data. Return rows follow the same signed-value
convention as real data (ADR-0004): `unit_mrp` stays positive, and
`quantity`/`mrp_value`/`net_value`/`discount_value` all flip sign together.

Three dedicated brands were generated, each with 300 stores / 8,000
products / 3 financial years:

| Brand | Rows | Stores | Products |
|---|---|---|---|
| LOADTEST_ALPHA | 12,000,000 | 300 | 8,000 |
| LOADTEST_BETA | 12,000,000 | 300 | 8,000 |
| LOADTEST_GAMMA | 12,000,000 | 300 | 8,000 |

Combined with the existing real brands (Killer: 737,476 rows; Pepe:
16,370; Junior Killer: 38,545), the dataset totals **36,792,391 rows**,
comfortably inside the ~30–40M target.

Throughput measured at generation time: ~45,000–63,000 rows/sec per
brand; all 36M synthetic rows generated in about 12.6 minutes total.

## Materialized view sizes at this scale

| MV | Rows |
|---|---|
| `mv_sales_summary` | 1,789 |
| `mv_store_perf` | 254,927 |
| `mv_category_perf` | 4,828,316 |

`mv_category_perf` is by far the largest — it's the only one of the three
that includes `store_id` in its grain, so its row count multiplies by
store count per brand (300 stores × ~8,000 products × 7 categories worth
of category/sub_category combos, per brand).

`REFRESH MATERIALIZED VIEW CONCURRENTLY` for all 3 MVs across all brands
(`refresh_all()`) took **~222–262 seconds** (measured twice, both in that
range) at this scale. This runs asynchronously as part of the post-upload
Celery pipeline, not on the user-facing request path, so it doesn't
affect dashboard latency — but it's a real scaling cost worth tracking
into Phase 2 as more brands/history are added (see "Phase 2 note" below).

## Latency results

Measured directly against `apps.analytics.queries` functions and the
cache-aside layer (`apps.analytics.cache.get_or_compute`), post-refresh,
across the 3 synthetic brands (worst case: 300 stores) and the real Killer
brand (worst case among real brands).

### Before tuning

| Query | Killer (real) | LOADTEST (300-store synthetic) |
|---|---|---|
| `dashboard_summary` (cold) | 0.37–5.07 ms | 0.50–1.52 ms |
| `store_perf_top10` | 13–40 ms | 25–37 ms |
| `category_perf_top10` | **152 ms** | **500–580 ms** |
| `store_trend` (YoY) | ~4 ms | ~14 ms |
| cache-aside miss / hit | ~1 ms / ~0.2–0.9 ms | ~1.3 ms / ~0.2–0.3 ms |

Every query was comfortably inside the ~150 ms cold / ~20 ms warm
acceptance target *except* `category_perf_top10`, which exceeded it for
every brand tested — worst on the real brand too, not just the synthetic
extreme.

### Root cause

`EXPLAIN (ANALYZE, BUFFERS)` on the `category_perf_top10` SQL (`GROUP BY
category, sub_category` over `mv_category_perf`) showed a plain Index
Scan on the existing `(brand_id, category, sub_category, gender,
store_id, ...)` unique index — matching rows still required a heap fetch
each: 819,066 buffer hits + 55,171 disk reads for the 1.58M matching rows
of one synthetic brand.

### Fix: covering index

`backend/apps/analytics/migrations/0003_category_perf_covering_index.py`
adds:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS mv_category_perf_brand_cat_covering
    ON mv_category_perf (brand_id, category, sub_category)
    INCLUDE (mrp_value, net_value, discount_value, quantity);
```

`INCLUDE`-ing the four `SUM`-ed measure columns lets Postgres satisfy the
whole query from the index alone — an **Index Only Scan**, no heap access
at all. `CREATE INDEX CONCURRENTLY` (not a plain `CREATE INDEX`) so this
is safe to run against a live table with traffic, matching this
codebase's existing `REFRESH MATERIALIZED VIEW CONCURRENTLY` discipline;
the migration uses `atomic = False` since `CONCURRENTLY` can't run inside
a transaction block.

### After tuning

| Brand | Before | After |
|---|---|---|
| Killer (real) | 152 ms | **8–24 ms** (13–19x) |
| LOADTEST_ALPHA | ~570 ms | **124–233 ms** (~3x) |
| LOADTEST_BETA | ~570 ms | **121–245 ms** (~3x) |
| LOADTEST_GAMMA | ~570 ms | **118–210 ms** (~3x) |

`EXPLAIN ANALYZE` after the fix confirms a `Parallel Index Only Scan`
with Heap Fetches down to ~65 (from tens of thousands).

The real Killer brand is now well inside target. The three synthetic
300-store brands land at 118–245 ms — close to, and sometimes slightly
over, the ~150 ms target, depending on OS page-cache state. This residual
cost is proportional to genuinely summing a large matched row set (300
stores/brand is beyond any real brand's actual scale in this dataset), not
a missing index — a coarser rollup MV would be the next lever if a real
brand ever approaches that store count, but isn't warranted now.

### `mv_store_perf` — considered, not changed

`store_perf_top10` was already comfortable (13–40 ms) before any tuning.
`EXPLAIN (ANALYZE, BUFFERS)` on the largest synthetic brand shows a plain
parallel `Seq Scan` over `mv_store_perf` (only ~85K rows for that brand)
completing in ~25 ms — nowhere near needing a covering index. Deliberately
left as-is rather than adding an index with no measured benefit.

## Cache-aside layer

Redis cache-aside (`analytics_cache.get_or_compute`/`bust`) round-trip
times: miss ~0.8–1.3 ms (includes the underlying query), hit ~0.2–0.3 ms.
Both are far under the ~20 ms warm target — the cache layer was never the
bottleneck at this scale.

## Result vs Day 11 acceptance criteria

- **Cold dashboard < ~150 ms (MV):** met for `dashboard_summary`,
  `store_perf_top10`, `store_trend` on every brand; `category_perf_top10`
  met on real brands after the covering-index fix, close-to-met on the
  synthetic 300-store extreme (documented above, not further pursued).
- **Warm < ~20 ms (cache):** met — cache hits measured at 0.2–0.3 ms.
- **Load test documented:** this document.

## Post-load-test cleanup

The three `LOADTEST_*` brands were deactivated (`active=False`) after
measurement — `GET /api/masterdata/brands/` filters on `active=True`
(`apps/masterdata/views.py`), so they no longer appear in the live brand
selector. Their rows remain in the database (not deleted) so the
measurement is reproducible without regenerating 36M rows.

## Phase 2 scaling note

**Correction (2026-07-12): this is user-facing, not just an async
post-upload cost.** `refresh_all()` runs synchronously inside
`process_upload_batch`/`execute_backfill` -- a batch doesn't reach
`loaded` until it finishes, so its cost is directly what the uploader
waits on. This was confirmed the hard way: with the Day 11 load-test
brands' ~36.8M rows still sitting in this dev database (deactivated, but
not deleted), a real user-reported "upload is slow" traced straight back
to `refresh_all()` taking ~238 seconds, because it refreshes materialized
views across *every* brand combined, not just the one being uploaded.
Deleting that synthetic data (a one-time partition-drop cleanup, not a
code change) brought it down to ~4.5s; a full realistic re-upload
end-to-end (conflict detection, slice replace, refresh) now takes 3.4s.

At real Phase-1 scale (the 3 real brands, ~800K rows total) this was
never the bottleneck. It becomes one again as more brands/history
accumulate, since every brand's upload pays for refreshing every other
brand's MVs too. Worth revisiting if Phase 2 adds enough brands/history
to bring this back — options at that point would include refreshing only
the affected brand's MV partitions (if MVs are ever partitioned per
brand) or moving to incremental/materialized-view maintenance instead of
a full concurrent refresh.
