# Retail Analytics Platform — Implementation Plan

**Owner:** 1 developer · **Phase 1 target:** 10–12 working days · **Doc status:** approved to build after schema freeze

This plan is the single source of truth for delivery. Phase 1 is detailed day-by-day with tasks, deliverables, git commits, and acceptance criteria. Phase 2 is outlined at the end and will be expanded into the same day-wise detail once Phase 1 ships.

---

## 1. Confirmed decisions (frozen — do not relitigate mid-sprint)

These are locked from client discussion. Any change is a formal scope change.

| # | Decision |
|---|---|
| Domain | Multi-brand apparel/footwear tertiary-sales analytics; India (INR, Apr–Mar FY, GST-inclusive values) |
| Tenancy | **Single company, multiple brands.** Brand is a dimension, not a tenant. No multi-tenant isolation in Phase 1. |
| Brands | 5–6 now; design for ~5× data growth. |
| Users | 2–3 concurrent, mostly Super Admin. |
| Auth | Email/password in Phase 1. SSO deferred. |
| Volume | Historical ~748k rows/brand; monthly incremental ≤ 25k/brand. Total ≈ 4–5M rows. |
| Formats | **Every brand has a different file format; formats are stable (client controls them).** → per-brand mapping config, not versioned. |
| Product lines | Data is menswear today; womenswear/kids/footwear will follow and **will add new attributes**. → mapping config keyed by **(brand, product_line)**; unmapped columns captured in `extra` JSONB (never break ingestion); new filterable attributes promoted via an **attribute registry** (additive migration, no redesign). |
| Row uniqueness | **No natural unique key.** Duplicate lines are legitimate. → surrogate PK + slice-replace (below). |
| Idempotency / corrections | Re-upload = **replace**. Corrections are **store-specific**. → replace unit = **(brand, store, month)**. |
| Authoritative date | Per brand, via mapping (e.g., Killer = NEW DATE). |
| Season / FY / Month | **Supplied by client, trusted as-is. Do NOT derive from date.** Keep raw for audit. |
| Store code | Unique **within a brand** → store key = (brand_id, store_code). |
| Product identity | Barcode (EAN/STOCKNo) = SKU key; article/style code (ITEM NAME/PC9) = article grouping. |
| Category hierarchy | Category (MAIN CATEGORY / GEN-CAT) → Sub-Category (CATEGORY). Gender = optional dimension (only some brands supply it). |
| Returns | Negative rows (negative MRP/qty/net). Flow into fact; net out in aggregation. |
| Discount % | **Always computed** = 100 − (net/mrp × 100), guarded against divide-by-zero. Supplied % used only to validate. |
| Phase 1 scope | Sales analytics + ingestion + RBAC + performance + deploy. |
| Phase 2 scope | SoH reconciliation, CN calculation, data-impurity UI, recommendation engine, promo/L2L analytics, SSO. |

**Open (non-blocking, resolve during sprint):** return-row sign consistency; single vs multi-month files; explicit store-month deletion case; zero-value/GWP examples.

---

## 2. Tech stack (final)

| Layer | Choice |
|---|---|
| Database | PostgreSQL 16 (declarative partitioning, materialized views, JSONB) |
| Cache / broker | Redis 7 |
| Backend | Python 3.12, Django 5 + Django REST Framework |
| Background jobs | Celery + Redis (RQ acceptable fallback) |
| Ingestion | pandas + openpyxl, bulk load via `COPY` |
| Frontend | React 18 + Vite + Ant Design + ECharts |
| Object storage | S3-compatible (Cloudflare R2 / Backblaze B2; MinIO in dev) |
| Deploy | Docker Compose on a single VPS; nginx (static + reverse proxy); TLS via Caddy/certbot |
| CI | GitHub Actions: lint + test on every push |

Rationale, alternatives, and migration paths are in `Retail_Analytics_Platform_Architecture.md`.

---

## 3. Canonical schema (target)

**Dimensions**
- `dim_brand(brand_id, brand_code, brand_name, active, created_at)`
- `brand_upload_config(config_id, brand_id, product_line, name, column_map JSONB, date_source, validation_rules JSONB, active)` — maps a **(brand, product_line)**'s columns → canonical fields; picks the authoritative date column. Keyed by product line so the same brand's menswear and womenswear files can differ. Any source column not in `column_map` is routed to `extra` JSONB rather than dropped.
- `dim_store(store_id, brand_id, store_code, store_name, city, state, zone, store_type, distributor_name, extra JSONB)` — `UNIQUE(brand_id, store_code)`.
- `dim_product(product_id, brand_id, barcode, article_code, item_name, main_category, category, sub_category, gender, fit, color, size, print_type, extra JSONB)` — `UNIQUE(brand_id, barcode)`. `extra` holds line-specific attributes (e.g., neckline, sleeve, occasion, heel height) until/unless promoted.
- `dim_calendar(date_id, date, day, month_no, month_name, quarter, financial_year)`.
- `dim_season(season_id, season_code, season_type, season_year, sort_order)` — supplied values (SS25/AW25/collection names) normalized here.
- `attribute_registry(attr_id, canonical_name, source, is_filterable, is_dimension, data_type, active)` — declares which canonical attributes the filter/analytics layer exposes and where they live (a real column vs a JSONB path). Adding a womenswear attribute to filters = a registry row (+ optional index), not a code deploy.

**Fact**
- `fact_sales(sale_id BIGINT GENERATED, brand_id, store_id, product_id, date_id, season_id, invoice_no, quantity, unit_mrp, mrp_value, net_value, discount_value, is_return, extra JSONB, upload_batch_id, source_row_no, created_at)`
  - `PARTITION BY LIST (brand_id)` → sub-`PARTITION BY RANGE (sale_date)` per financial year.
  - Non-unique index on `(store_id, invoice_no, product_id)` for query + duplicate reporting.
  - `extra JSONB` = row-level safety valve for unmapped/line-specific measures; keeps ingestion unbreakable on new columns.
  - `discount_pct` computed in views, never stored.

**Ingestion / ops**
- `upload_batch(batch_id, brand_id, config_id, uploaded_by, file_name, object_key, status, row_count, error_count, slices JSONB, error_report_key, started_at, finished_at)` — `status ∈ {received, parsing, validating, failed, loaded, rolled_back}`; `slices` = list of (store, month) replaced.

**Materialized views**
- `mv_sales_summary` (brand × FY × month × season → Σ mrp, net, discount, qty)
- `mv_store_perf` (brand × store × period → net, mrp, qty, discount)
- `mv_category_perf` (brand × category × sub_category × store × period → net, qty, discount)

**Idempotent load (store-month replace):** for each `(brand, store, month)` present in an upload → `DELETE` existing fact rows for that slice, then bulk-`INSERT` new rows in one transaction; refresh affected MVs; bust cache. No natural key needed.

**Extensibility principle (mens → womens/kids/footwear):** the ingestion pipeline is container-agnostic (CSV/XLSX/XLS) and column-tolerant. New product-line **values** (gender, categories, sizes, colors) are auto-created as dimension rows during load — zero changes. New/unknown **columns never break ingestion** — they are captured in `extra` JSONB and preserved. A new file **layout** for a product line is a new `(brand, product_line)` mapping config — data, not code. Promoting a captured attribute to a **first-class filter/dimension** is an additive step: backfill from `extra` → add column/index → add an `attribute_registry` row. This deliberately avoids EAV (which would wreck query performance) while keeping onboarding of new lines cheap and non-breaking. What is *not* automatic, by design: deciding the business meaning of a brand-new attribute (that's a mapping/registry decision, done once per attribute).

---

## 4. Repository & conventions

```
repo/
  backend/            # Django project
    apps/
      accounts/       # users, RBAC
      masterdata/     # brands, stores, products, configs, admin
      ingestion/      # upload, parse, map, validate, load, batches
      analytics/      # read-path (raw SQL over MVs), filters, trends
    core/             # settings, celery, db routing
    tests/
  frontend/           # React + Vite + AntD
  ops/                # docker-compose, nginx, backup scripts, runbooks
  docs/               # architecture, plan, ADRs
  .github/workflows/  # CI
```

- **Branching:** short-lived feature branches → PR → `main`. `main` is always deployable.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `perf:`, `test:`, `docs:`, `ci:`).
- **Definition of Done (every day):** migrations apply cleanly, tests pass in CI, lint clean, feature demoable, branch merged to `main`.
- **Testing:** pytest (backend) with 2 real brand fixtures (Killer + Pepe); Vitest/RTL for critical frontend; one end-to-end smoke path.

---

# PHASE 1 — Trustworthy Sales Analytics

Goal: a deployed platform where an admin uploads any brand's file and immediately sees correct, fast dashboards (Dashboard, Store-wise, Category-wise, Trends) with extensive filtering, behind role-based auth. Days assume ~6–7 focused hours. Days 5–6 (ingestion) are highest-risk and front-loaded.

---

## Day 0 — Kickoff & schema freeze (½ day)

**Status:** ✅ Done (2026-07-05). Grounded against the two real seed files
(`KILLER - EAN CODE WISE SALE 23-24 TO 25-26.xlsb`,
`PEPE BIHAR DSR REPORT 2026.xlsb`) rather than assumption alone — see
`docs/schema.md` for the full column trace and `docs/adr/0002-*.md` for two
open items resolved empirically (return-row sign consistency; multi-month
single-file uploads).

**Goals:** lock the canonical schema against real files; set up accounts.

**Tasks**
- Re-confirm the frozen decisions (§1) with client sign-off.
- Map both real files (Killer, Pepe) column-by-column to canonical fields; write the two `column_map` JSONB drafts.
- Provision: GitHub repo, object-storage bucket (R2/B2), a dev VPS or local Docker, domain.
- Write ADR-0001 (stack) and ADR-0002 (no-natural-key + store-month replace).

**Deliverables:** frozen schema doc + two mapping configs + provisioned accounts.
**Commits:** `docs: adr-0001 stack`, `docs: adr-0002 ingestion key strategy`, `docs: canonical schema + brand mappings`.
**Acceptance:** every column in both sample files has a canonical target or an explicit "ignore".

---

## Day 1 — Foundation & skeleton

**Status:** ✅ Done (2026-07-05). Verified end-to-end on a fresh volume:
`docker compose up --build` migrates cleanly, `/health/` returns 200
(DB+Redis+broker) both directly and via nginx, `pytest`/`ruff`/`black` are
clean in the backend container, and `npm run lint`/`npm run build` are clean
in the frontend container.

**Goals:** reproducible dev environment; empty but running system.

**Tasks**
- `docker-compose.yml`: postgres, redis, backend (Django+gunicorn), celery worker, frontend dev, nginx.
- Django project + apps scaffolding (`accounts`, `masterdata`, `ingestion`, `analytics`); settings via env; Postgres + Redis wired; Celery configured.
- `/health` endpoint (checks DB + Redis + broker).
- GitHub Actions: lint (ruff/black), pytest, frontend build; pre-commit hooks.

**Deliverables:** `docker compose up` boots the full stack; health endpoint green; CI passing.
**Commits:** `chore: scaffold docker-compose`, `chore: django project + apps`, `feat: health endpoint`, `ci: lint+test pipeline`.
**Acceptance:** fresh clone → `docker compose up` → health 200; CI green on PR.

---

## Day 2 — Data model & partitioned fact

**Status:** ✅ Done (2026-07-05), pending your review (this is a review gate).
Verified against a real Postgres 16 instance from a fresh volume: all 7
dimension tables + `fact_sales` migrate cleanly, `seed_brands`/`seed_calendar`
run end-to-end, creating a brand auto-creates its `fact_sales_bN` LIST
partition, inserting a row auto-routes into the right `_fyNNNN` RANGE
sub-partition, and both `UNIQUE(brand,store_code)`/`UNIQUE(brand,barcode)`
and out-of-range inserts are rejected. One schema correction found by a real
test failure (not by inspection) is documented in `docs/schema.md` Sec "Day 2
implementation notes": the PK had to become `(brand_id, sale_date, sale_id)`,
not `(brand_id, sale_id)`, because Postgres requires a partitioned table's
unique indexes to cover every partitioning level, not just the top one.

**Goals:** the full canonical schema exists and is tested.

**Tasks**
- Migrations for all dimensions + `dim_season` + `dim_calendar`, each with an `extra JSONB` column where noted (safety valve for future product lines).
- `fact_sales` as `PARTITION BY LIST(brand_id)`; helper to auto-create a brand partition + yearly sub-partitions on brand creation / first upload.
- Calendar seeder (dates + FY + quarter; FY = Apr–Mar). Season rows created on ingest (supplied values), not derived.
- Indexes: FK b-tree indexes; non-unique `(store_id, invoice_no, product_id)`; BRIN on `sale_date` within partitions.
- Constraints: `UNIQUE(brand_id, store_code)`, `UNIQUE(brand_id, barcode)`.

**Deliverables:** migrations apply; partitions auto-create; seed script loads dims for 2 brands.
**Commits:** `feat: dimensional schema`, `feat: partitioned fact_sales + partition automation`, `feat: calendar seeder`, `test: schema constraints & partition routing`.
**Acceptance:** inserting rows for a new brand auto-routes to its partition; constraint violations rejected in tests.

---

## Day 3 — Auth & extensible RBAC

**Status:** ✅ Done (2026-07-05). Custom email/password `User` model (swapped
in via `AUTH_USER_MODEL` before any real deployment, so no migration
surgery needed), JWT auth (login/refresh/logout-via-blacklist) through
`djangorestframework-simplejwt`, a password-reset stub, and RBAC built
purely on Django Groups + Permissions -- `seed_roles` gives Super Admin
*every* permission that exists (idempotent, self-updating as new models
appear) and Data Inserter a curated view-only set today, extended in Day 4
once `upload_batch` exists. All permission checks are capability-based
(`user.has_perm(...)`), never role-name checks. 26/26 tests pass, verified
end-to-end through nginx from a fresh volume (login, `/me`, admin session
login all confirmed live, not just in tests) -- which is how a real nginx
bug got caught: static `proxy_pass` cached the backend container's IP at
nginx startup, so recreating the backend (any redeploy) 502'd until nginx
was restarted; fixed with `resolver` + variable-based `proxy_pass` so nginx
re-resolves container names per request. Documented as a `fix:` commit.

**Goals:** login and role-gated access; admin for master data.

**Tasks**
- Custom `User` model; JWT (or session) auth; login/logout/refresh; password reset stub.
- RBAC on Django Groups + custom permissions; seed **Super Admin** (all) and **Data Inserter** (upload + view). Permission checks are on capabilities, not role names (extensible).
- Django admin enabled for brands/stores/products/configs (Super Admin only).
- DRF permission classes wired to endpoints.

**Deliverables:** working login; protected endpoints; admin manages master data.
**Commits:** `feat: custom user + auth`, `feat: extensible rbac (groups+permissions)`, `feat: django admin for masterdata`, `test: permission matrix`.
**Acceptance:** Data Inserter blocked from admin endpoints; Super Admin full access; tests cover both roles.

---

## Day 4 — Brand mapping config + upload intake

**Status:** ✅ Done (2026-07-05). `seed_upload_configs` loads the real Day 0
Killer/Pepe configs (relocated from `docs/mapping-configs/` into
`backend/apps/masterdata/seed_data/` so they're actually inside the Docker
build context); `seed_attribute_registry` seeds the 14 Phase-1 filterable
attributes. Object storage is a thin boto3 wrapper (MinIO in dev via a new
compose service, same code path as R2/B2 in prod) with immutable, uniquely-
keyed uploads. `UploadBatch` + the upload endpoint are built exactly to the
architecture's split: the endpoint only stores bytes, creates the batch, and
enqueues a Celery task -- it never reads file contents; a first slice of the
mapping engine (`column_resolver.resolve_columns`) is tested against the
real Killer/Pepe configs plus a synthetic unmapped column, proving the
"never drop a column" routing decision, ahead of Day 5 building the rest of
the pipeline on top of it. Verified live, not just in tests: uploaded a
synthetic file through nginx with a real JWT-authenticated Data Inserter
user, watched the Celery worker pick up the task and flip the batch to
`parsing` within milliseconds, and confirmed the file landed immutably in
MinIO. Also completed a Day-2 loose end: `fact_sales.upload_batch_id` now
has its real FK constraint to `upload_batch`, deferred since Day 2 because
the table didn't exist yet. 48/48 tests pass (added a MinIO step to CI,
since GitHub Actions' `services:` block can't override a container's
command and MinIO needs `server /data`).

**Goals:** per-brand mapping stored & editable; raw files captured; jobs enqueued.

**Tasks**
- `brand_upload_config` model keyed by **(brand, product_line)** + admin editor (`column_map`, `date_source`, `validation_rules`). Load the two real mappings from Day 0. Unmapped columns route to `extra` JSONB by default.
- `attribute_registry` model + seed it with the Phase-1 canonical filterable attributes (brand, store, city/zone, category, sub-category, gender, color, fit, size, season, FY, month, discount range). This is what the filter engine (Day 8) reads.
- Object-storage client (put/get, presigned); store every raw upload immutably.
- `upload_batch` model + upload endpoint: accept CSV/XLSX/XLS, resolve the (brand, product_line) config, store raw → create batch (`received`) → enqueue Celery job. Returns batch id for polling.

**Deliverables:** upload a real file → raw stored → batch created → job queued; unknown columns land in `extra`, not dropped.
**Commits:** `feat: (brand,product_line) upload config + admin`, `feat: attribute registry + seed`, `feat: object storage client`, `feat: upload endpoint + upload_batch`, `test: upload intake + unmapped-column capture`.
**Acceptance:** Killer and Pepe files create batches with correct config; a synthetic file with an extra unknown column ingests with that column preserved in `extra`.

---

## Day 5 — Ingestion: parse → map → validate (HIGH RISK)

**Goals:** turn any brand's messy Excel into clean, validated canonical rows or a clear error report.

**Tasks**
- Worker step 1: read Excel with pandas (chunked at 100k); normalize headers.
- Step 2: apply `column_map` → canonical frame; coerce types; parse the brand's authoritative date; normalize season/category/size text; compute `mrp_value`, `discount_value`; derive `is_return` (negative values); compute discount% for validation.
- Step 3: validation rules — required fields present, numeric sanity, store resolves/creates in `dim_store`, product resolves/creates in `dim_product`, discount% vs supplied within tolerance. Collect row/column/reason errors.
- On errors → batch `failed` + downloadable structured error report (Excel/CSV) → nothing loaded.

**Deliverables:** bad file → precise error report; clean file → validated staging frame + resolved dim keys.
**Commits:** `feat: excel parse + header normalize`, `feat: column mapping + type coercion`, `feat: validation engine + error report`, `test: ingestion fixtures (killer+pepe, good & bad)`.
**Acceptance:** deliberately corrupted fixtures produce actionable reports; clean fixtures validate 100%.

---

## Day 6 — Ingestion: load, store-month replace, MV refresh (HIGH RISK)

**Goals:** idempotent load into the partitioned fact with correct correction semantics.

**Tasks**
- `COPY` validated rows into an `UNLOGGED` staging table.
- Determine `(brand, store, month)` slices in the batch; within one transaction: `DELETE` existing fact rows per slice → `INSERT … SELECT` from staging → tag `upload_batch_id`, `source_row_no`.
- Upsert `dim_store` / `dim_product` / `dim_season` as needed.
- Refresh affected materialized views (targeted, `CONCURRENTLY`); bust Redis keys for the brand; set batch `loaded` with counts + slices.
- Batch rollback (delete by `upload_batch_id`).

**Deliverables:** end-to-end upload → queryable facts; re-upload of a store's month replaces cleanly with no duplicates; returns net correctly.
**Commits:** `feat: staging COPY loader`, `feat: store-month replace + idempotent merge`, `feat: mv refresh + cache bust`, `feat: batch rollback`, `test: re-upload idempotency + returns netting`.
**Acceptance:** uploading April twice yields identical totals; a store-only correction changes only that store; a negative row reduces net sales.

---

## Day 7 — Materialized views + analytics read-path

**Goals:** fast, correct aggregate APIs.

**Tasks**
- Create `mv_sales_summary`, `mv_store_perf`, `mv_category_perf` with unique indexes (for `REFRESH CONCURRENTLY`).
- Analytics service in raw SQL over MVs (never scans raw fact). Endpoints: dashboard summary (total/MRP/net sales, total discount by season), store-wise (top-10), category-wise (top-10, order by net/qty/discount%).
- Redis cache-aside keyed by filter-hash; TTL + explicit bust on that brand's upload.

**Deliverables:** three analytical APIs returning correct, cached numbers.
**Commits:** `feat: aggregate materialized views`, `feat: analytics read-path (raw sql)`, `feat: redis cache-aside`, `test: aggregate correctness vs hand-computed fixtures`.
**Acceptance:** API totals match manually computed fixture totals to the paisa; warm calls served from cache.

---

## Day 8 — Filter engine + trends API

**Goals:** the "extensive filtering" requirement and all trend views.

**Tasks**
- Composable filter engine driven by `attribute_registry` (not hardcoded) → SQL: brand, store, city/zone, category, sub-category, gender, color, fit, size, season, financial year, month, discount range, article/style. New attributes become filterable by adding a registry row + index — no engine rewrite.
- Discount-range handled via precomputed buckets in MVs for index-friendliness.
- Trends endpoints: store / category / sub-category performance as YoY, MoM, and Season-by-Season on net sales, MRP sales, and quantity; optional store scoping.

**Deliverables:** every documented filter + all top-10 orderings + trend series available via API.
**Commits:** `feat: composable filter engine`, `feat: discount-range buckets`, `feat: trends yoy/mom/season`, `test: filter matrix + trend math`.
**Acceptance:** filter combinations return correct subsets; YoY/MoM/Season math verified against fixtures.

---

## Day 9 — Frontend shell + Dashboard view

**Goals:** usable app with the main dashboard.

**Tasks**
- React/Vite/AntD app; auth flow (login, token handling, route guards by role); app layout + nav.
- Global filter bar (brand, season, FY, month, store, category…) with shared state.
- Dashboard view: Total Sales / MRP Sales / Net Sales / Total Discounts cards + ECharts breakdowns by season.

**Deliverables:** log in → filter → see live dashboard from the API.
**Commits:** `feat: react app shell + auth guards`, `feat: global filter bar`, `feat: dashboard view + charts`.
**Acceptance:** dashboard reflects filters live; unauthorized routes blocked.

---

## Day 10 — Store-wise & Category-wise views + Upload UI

**Goals:** the remaining analytical screens and the upload experience.

**Tasks**
- Store-wise view: top-10 store table (net, MRP, qty, discount%), brand/year/month filters, sortable columns.
- Category-wise view: category/sub-category tables with store multi-select; order by net sales / quantity / discount%.
- Upload screen: file picker, brand select, progress polling, batch status, and error-report download on failure.

**Deliverables:** all core screens usable end-to-end, including upload with feedback.
**Commits:** `feat: store-wise view`, `feat: category-wise view`, `feat: upload UI + batch status + error download`.
**Acceptance:** a non-technical user can upload a file and read all three views without help.

---

## Day 11 — Trends UI, hardening, load test

**Goals:** finish features; prove performance at realistic scale.

**Tasks**
- Trends UI (YoY/MoM/Season toggles, entity/store selectors, ECharts).
- Empty/error/loading states; input validation; consistent currency/number formatting (INR).
- Generate synthetic ~30–40M rows across brands; measure dashboard/filter latency; tune indexes, MV shapes, and cache TTLs from real numbers.

**Deliverables:** complete Phase-1 feature set; measured sub-second dashboards on realistic data.
**Commits:** `feat: trends ui`, `feat: ux states + inr formatting`, `perf: index/mv/cache tuning`, `test: load test + e2e smoke`.
**Acceptance:** cold dashboard < ~150 ms (MV), warm < ~20 ms (cache); load test documented.

---

## Day 12 — Deploy, backups, docs, handover

**Goals:** production live and operable.

**Tasks**
- Provision prod VPS; production `docker-compose` + nginx/Caddy + TLS; env/secrets management.
- Nightly `pg_dump` → object storage with retention; **tested restore runbook** (target < 30 min).
- Seed initial Super Admin; load real historical files per brand (backfill: COPY then build indexes/MVs).
- README + ops runbook + architecture/plan in `docs/`; tag `v1.0.0`.

**Deliverables:** production URL live; backups verified by a test restore; docs complete; historical data loaded.
**Commits:** `chore: prod compose + tls`, `ops: automated backups + restore runbook`, `docs: readme + ops handover`, `release: v1.0.0`.
**Acceptance:** client logs into production, sees real historical dashboards; a restore drill succeeds.

**Buffer:** if only 10 days, compress Day 11 polish and move trends-UI refinement + synthetic load test into a post-launch buffer day; core features (Days 1–10) and deploy stay intact.

---

## Phase 1 — verification & exit criteria

- [ ] Any brand's file uploads via its mapping config; bad files produce actionable error reports.
- [ ] Re-upload replaces (brand, store, month) with zero duplication; returns net correctly.
- [ ] Dashboard, Store-wise, Category-wise, Trends all correct vs hand-computed fixtures.
- [ ] All documented filters work; discount% computed consistently.
- [ ] RBAC enforced (Super Admin, Data Inserter); admin manages master data.
- [ ] Sub-second dashboards on ~30–40M synthetic rows.
- [ ] Deployed, TLS, nightly backups, tested restore, docs + `v1.0.0`.

---

# PHASE 2 — Reconciliation & Intelligence (preview)

To be expanded into day-wise detail after Phase 1 ships. Indicative scope and sequence:

1. **SoH reconciliation** — ingest secondary-sales, dealer-stock (submitted SoH), goods-return via the *same* mapping/ingestion pipeline. `Calculated SoH = Σ secondary − Σ tertiary (± returns)` at brand & store grain. Compare to submitted → RAG status (Green match / Red calc<submitted / Amber calc>submitted). Reconciliation UI matching the client's table.
2. **CN (Credit Note) calculation** — pending business formula from client; module + UI once defined.
3. **Data-impurity detection & correction UI** — promote the Day-5 validation findings from hard failures to reviewable, fixable items in the UI (the "stretch goal").
4. **Recommendation engine** — start with transparent statistical baselines (season-over-season growth, store/category momentum, ABC/velocity, inventory movement) for horizons monthly / quarterly / seasonal, max 2 seasons ahead. Introduce ML only if it measurably beats the baseline. Targets: stores to focus, categories to push, inventory movement, sales opportunities.
5. **Promo & L2L analytics** — Fresh vs EOSS vs Offer segmentation; like-for-like (comparable-store) trends, where brands supply the data.
6. **Platform hardening** — SSO, optional managed Postgres migration, read replica if load demands.

---

## Infrastructure cost (Phase 1)

| Item | Spec | ~Monthly |
|---|---|---|
| VPS (app + DB + Redis + worker) | 4–8 vCPU / 8–16 GB / SSD | $20–40 |
| Object storage (raw files + backups) | tens of GB, low egress | $1–5 |
| Domain + TLS | Let's Encrypt free | ~$1 |
| **Total** | | **~$25–45 / month** |

Managed-cloud equivalent (RDS + ElastiCache + ECS + S3 + ALB) ≈ $150–350/mo — deferred until SLA/scale justify it; migration path documented in the architecture doc.
