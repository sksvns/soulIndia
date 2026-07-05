# Retail Analytics Platform — Engineering Design (Phase 1)

**Prepared as:** Principal Engineer architecture review
**Constraint:** 1 developer, 10–12 days to Phase 1, minimum infra cost, clean migration path
**Domain (inferred):** Apparel/footwear multi-brand tertiary-sales analytics (Killer, Pepe, Kraus, GoColors…), India (INR, "lakh", Apr–Mar FY, GST)

---

## 0. Executive summary — the decisions

1. **This is not big data.** Worst realistic case is ~100–150M rows total (see sizing). PostgreSQL with partitioning + indexes + materialized views + Redis handles this with sub-second dashboards. **No Spark, Kafka, ClickHouse, or microservices.** They would add operational cost and multiply delivery risk for a solo dev, buying nothing at this scale.
2. **The real hard problem is not analytics — it is ingestion.** "Every brand has its own upload format" is the single biggest risk in Phase 1. The architecture is built around a **configurable, per-brand column-mapping ingestion pipeline** feeding one canonical star schema. Get this right and everything downstream is easy.
3. **A modular monolith, not microservices.** One deployable backend with clean internal module boundaries (ingestion / analytics / auth / admin). Migratable to services later only if a real bottleneck appears.
4. **Recommended stack:** PostgreSQL 16 + Redis + **Django + Django REST Framework** (backend) + **React (Vite) + Ant Design + ECharts** (frontend) + a background worker (Celery/RQ or Postgres-backed) + object storage for raw uploads. Deployed as **Docker Compose on a single VPS** in Phase 1.
5. **Cost:** ~**$25–45/month** in Phase 1 (single VPS + object storage + backups). Managed-cloud equivalent would be $150–350/mo and is not justified yet.
6. **SoH reconciliation, CN, data-impurity UI, and the recommendation engine are Phase 2.** Phase 1 delivers sales analytics (dashboard, store-wise, category-wise, trends), ingestion, RBAC, and the performance layer. Attempting SoH + recommendations in 12 days solo would compromise quality on the foundation.

---

## 1. Clarification questions (must-answer before/at kickoff)

I have grouped these by whether they **block** the data model (answer before I write migrations) vs. can be answered during the sprint.

### A. Blocking — needed before the canonical schema is frozen (Day 1–2)

1. **How many brands total, now and at 5× growth?** Sizing and partition strategy depend on it. Examples imply ~6–15; confirm the ceiling.
2. **What is the grain of one Excel row?** Is each row one invoice line (article + color + size + qty), or a pre-aggregated store/day total? All analytics ("ordered by quantity", "discount %", category/color/subcategory filters) assume **line-item grain**. Confirm.
3. **Canonical field list.** Which of these are present in *every* brand's file, and which are optional: `invoice_no, invoice_date, store, article/style code, category, sub_category, article_type, color, size, MRP, NSV, discount_value, quantity`? Anything that isn't universal becomes nullable/derived.
4. **Value definitions & tax.** Confirm: `MRP Sale = qty × MRP`; `NSV = Net Sales Value` = value actually realised. Are MRP/NSV **inclusive or exclusive of GST**? Is discount computed per line or per invoice? The doc gives `Discount % = 100 − (NSV/MRP×100)` — confirm this is the single source of truth.
5. **Season definition.** Exact month→season mapping. Standard apparel is SS = Jan–Jun, AW = Jul–Dec — confirm, and confirm season is derived from `invoice_date` (not a column in the file). Is financial year **Apr–Mar**?
6. **Invoice uniqueness at line grain.** Note #9 says uniqueness = Store + Invoice Number. But at line grain a store+invoice has many rows. Is the true unique key **(store, invoice_no, article, size)**, or is there a line number? This decides duplicate-detection and idempotent re-upload logic.
7. **Re-upload / correction semantics.** If a brand re-uploads the same month, do we **replace** that (brand, month) partition, **upsert** by key, or **reject duplicates**? This is critical for monthly incremental integrity.
8. **Category taxonomy ownership.** Are Category / SubCategory / ArticleType provided inside each brand's file, or maintained as master data we control and map to? Cross-brand consistency of these values drives the whole filtering experience.

### B. Important — can be answered during the sprint

9. **Multi-tenancy model.** One client company that owns all these brands (single tenant, brand = a dimension)? Or are you selling this to multiple companies (true SaaS multi-tenant, needs row-level isolation from Day 1)? This changes auth and data-scoping design; I've assumed **single tenant, brand as a filter** for Phase 1 with a clean path to multi-tenant.
10. **Users & concurrency.** How many named users and expected peak concurrent dashboard users? (Drives cache sizing, not architecture.)
11. **Auth.** Email/password is fine for Phase 1? Or is SSO/Google Workspace required now?
12. **Monthly upload volume.** Rows per brand per month (drives worker sizing and MV-refresh strategy).
13. **Data residency.** Any requirement that data stay in India? (Picks the VPS region.)
14. **"CN Calculation" and "Goods return".** Need the exact formula/business meaning of Credit Note. Deferred to Phase 2 but define early.
15. **SoH inputs (Phase 2).** Frequency, grain, and format of secondary-sales and dealer-stock (SoH) submissions; are they per store, per article, monthly?

**My working assumptions if unanswered:** line-item grain; India Apr–Mar FY; SS=Jan–Jun / AW=Jul–Dec; values GST-inclusive; unique key (store, invoice_no, article, size); monthly re-upload = replace-partition for that (brand, month); single tenant with brand as a dimension; email/password auth.

---

## 2. Data sizing — why Postgres is the right call

| Scenario | Brands | Rows/brand (4 yrs) | ×5 growth | Total rows |
|---|---|---|---|---|
| Given | 1 | ~500k | 2.5M | 2.5M |
| Likely | 12 | 500k | 2.5M | ~30M |
| Pessimistic | 50 | 500k | 2.5M | ~125M |

Even the pessimistic 125M-row fact table is **routine** for PostgreSQL with monthly/brand partitioning. Dashboards never scan raw facts — they read **pre-aggregated materialized views** (a few thousand rows). ClickHouse only earns its keep at billions of rows or high-cardinality ad-hoc scans we don't have. **Verdict: PostgreSQL, decisively.**

---

## 3. Tech stack — decisions, alternatives, trade-offs, migration

Each component follows the required format: **Choice → Why → Alternatives → Trade-offs → Migration path → Risk.**

### 3.1 Database — PostgreSQL 16
- **Why:** One engine covers OLTP (uploads, users), analytics (window functions, `GROUPING SETS`, MVs), JSONB (per-brand mapping configs, raw-row staging), partitioning, and full-text if needed. Mature, cheap, solo-dev-friendly.
- **Alternatives:** ClickHouse (columnar) — rejected: unjustified at our scale, weak on updates/re-uploads, second system to operate. MySQL — weaker analytics SQL, no native declarative partitioning parity, poorer JSONB.
- **Trade-offs:** Heavy ad-hoc scans over 100M+ rows would be slower than columnar — mitigated by MVs so we never do that.
- **Migration path:** If a future analytics workload truly needs columnar, add ClickHouse **as a read replica for one heavy view** via CDC — the star schema ports directly. Postgres stays the system of record.
- **Risk:** Low. Main risk is bad partitioning/index choices → covered in HLD.

### 3.2 Cache / queue broker — Redis
- **Why:** Dashboard query-result cache (keyed by filter-hash), rate limiting, and broker for background jobs. Sub-ms reads.
- **Alternatives:** In-process cache — rejected (lost on deploy, no cross-worker sharing). Memcached — no persistence, fewer data structures.
- **Trade-offs:** One more process. On a single VPS it's trivial.
- **Migration:** Managed Redis (Elasticache/Upstash) is a connection-string change.
- **Risk:** Low. Cache is an optimisation, not a correctness dependency (cache-aside).

### 3.3 Backend — Django + Django REST Framework  **(primary recommendation)**
- **Why:** For a **solo dev on a 12-day clock**, Django gives, for free, the exact things this app needs and that would otherwise eat days: authentication, an **extensible role/permission system** (Groups + custom permissions → "Super Admin", "Data Inserter", and future roles), a batteries-included **admin UI** for master data (brands, stores, mapping configs), migrations (schema evolution), and a clean ORM that still lets me drop to **raw SQL for the analytics read-path**. This maximizes delivery speed and maintainability without hand-rolling plumbing.
- **Alternatives considered:**
  - **FastAPI + SQLAlchemy + Alembic** — lighter, async, great performance. **Rejected for Phase 1** because I'd have to hand-build auth, RBAC, admin, and wiring — 2–3 days I don't have. It's the better choice *if* the app were mostly a thin async API; here the CRUD/admin/RBAC surface is large. Reconsider at Phase 2+ if async I/O becomes a bottleneck.
  - **Node/NestJS** — fine, but Python wins because ingestion is pandas/openpyxl-heavy; keeping ingestion and API in one language reduces context-switching for a solo dev.
- **Trade-offs:** Django's sync model is less ideal for high-concurrency async I/O. Not a Phase-1 concern (dashboards are cache/MV-served; uploads are async via worker). The analytics endpoints use raw SQL, so the ORM's abstraction cost is avoided where it matters.
- **Migration path:** Analytics read-path is already decoupled (raw SQL over MVs) — it can be lifted into a separate FastAPI/Go read service later with zero data-model change. RBAC maps cleanly to any external IdP later.
- **Risk:** Medium-low. Main risk is treating the ORM as a hammer for analytics; mitigated by the explicit read-path/write-path split.

> If you have a strong existing FastAPI codebase/skillset, I'll switch — but my default recommendation under the time constraint is Django, and I'll defend it.

### 3.4 Ingestion — pandas + openpyxl inside a background worker
- **Why:** Excel parsing, type coercion, per-brand column mapping, validation, and bulk load are natural in pandas; `COPY`/`execute_values` for fast inserts.
- **Alternatives:** DB-native `COPY` only — can't handle heterogeneous formats/mapping. Streaming parsers — unnecessary at monthly file sizes.
- **Trade-offs:** pandas holds a file in memory; monthly files are small (MBs), fine. For very large historical back-loads, chunk the read.
- **Migration:** If files ever get huge, swap to chunked/streaming or Polars with no API change.
- **Risk:** Medium — messy real-world Excel. Mitigated by a strict validation + staging + error-report step (see ingestion design).

### 3.5 Background jobs — Celery + Redis (or RQ)
- **Why:** Uploads and MV refreshes must be async so the UI stays responsive; need retries, progress, and status.
- **Alternatives:** Synchronous request handling — rejected (long uploads block/timeouts). **Postgres-backed queue (e.g., `pg-boss`-style / `django-tasks`)** — a valid *lower-ops* alternative that removes Celery's complexity; acceptable if you'd rather avoid Celery. I lean Celery for maturity/visibility, but note RQ is simpler for a solo dev.
- **Trade-offs:** Celery adds a worker + config. RQ is simpler with fewer features.
- **Migration:** Broker/config swap.
- **Risk:** Low.

### 3.6 Frontend — React (Vite) + Ant Design + ECharts
- **Why:** AntD ships enterprise-grade tables, multi-select filters, date pickers, and forms out of the box → directly serves "extensive filtering" and top-10 tables fast. ECharts handles large series and rich interactions better than Recharts.
- **Alternatives:** shadcn/ui + Recharts — prettier/leaner but more assembly for complex tables/filters (slower for a solo dev on this deadline). Server-rendered Django templates — rejected: the filtering UX demands a SPA.
- **Trade-offs:** AntD is heavier and opinionated visually. Acceptable for an internal analytics tool; theming later if needed.
- **Migration:** Component-library swap is contained in the presentation layer; API contract is stable.
- **Risk:** Low.

### 3.7 Object storage — S3-compatible (Cloudflare R2 / Backblaze B2 / MinIO)
- **Why:** Keep every raw uploaded file immutable for audit, re-processing, and debugging. R2/B2 have near-zero egress cost.
- **Alternatives:** Store on VPS disk — acceptable early, but risks data loss and bloats backups. Store blobs in Postgres — rejected (bloat).
- **Migration:** S3 API is universal; move buckets freely.
- **Risk:** Low.

### 3.8 Deployment — Docker Compose on a single VPS (Phase 1)
- **Why:** Lowest cost, simplest to operate solo, fully reproducible. One `docker-compose.yml`: nginx (static React + reverse proxy) + Django (gunicorn) + worker + Postgres + Redis. Automated nightly `pg_dump` to object storage.
- **Alternatives:** Kubernetes — rejected outright (massive ops overhead, no benefit at this scale). Managed PaaS (Render/Railway/Fly) — slightly pricier but even simpler; acceptable if you value zero server maintenance over cost. Full managed AWS (RDS+ECS) — Phase 3, when scale/SLA demands it.
- **Trade-offs:** Single VPS = single point of failure; mitigated by daily off-box backups + a documented 30-min restore runbook. Vertical scaling to 16–32GB RAM buys enormous headroom before HA is needed.
- **Migration path (explicit):** Compose → managed Postgres (RDS/Cloud SQL) by pointing at a new DSN → containers to ECS/Cloud Run → add read replica → (only if ever needed) columnar/services. Nothing in Phase 1 blocks this.
- **Risk:** Medium (availability). Accepted deliberately for cost; revisit at real user load / SLA commitments.

---

## 4. High-Level Design (HLD)

### 4.1 Component view

```
                        ┌─────────────────────────────────────────┐
   Browser (React SPA)  │  Ant Design UI · ECharts · filter state  │
        │  HTTPS/JSON   └─────────────────────────────────────────┘
        ▼
   ┌───────────┐   static + reverse proxy
   │   nginx   │──────────────┐
   └───────────┘              ▼
                        ┌──────────────┐   read-path (raw SQL over MVs, cache-aside)
                        │  Django/DRF  │───────────────► Redis (result cache)
                        │  (gunicorn)  │
                        │  modules:    │───────────────► PostgreSQL 16
                        │  auth/rbac   │                  ├ OLTP tables
                        │  masterdata  │                  ├ fact_sales (partitioned)
                        │  ingestion   │                  ├ dim_* tables
                        │  analytics   │                  └ materialized views
                        └──────┬───────┘
                 enqueue upload│ job
                               ▼
                        ┌──────────────┐   parse→map→validate→stage→load→refresh MV
                        │ Celery worker│───► PostgreSQL   ◄── raw file ── Object Storage (R2/B2)
                        └──────────────┘
```

### 4.2 Canonical data model (star schema)

**Dimensions**
- `dim_brand(brand_id, name, code, upload_config_id)`
- `dim_store(store_id, brand_id, store_code, store_name, city, region)`
- `dim_product(product_id, brand_id, article_code, category, sub_category, article_type, color, size)` — or split category into its own `dim_category` if taxonomy is shared/curated (decided by Q8).
- `dim_calendar(date_id, date, month, financial_year, season)` — season & FY derived here once, reused everywhere.

**Fact (line grain)**
```
fact_sales(
  sale_id BIGINT,
  brand_id, store_id, product_id, date_id,     -- FKs to dims
  invoice_no TEXT,
  quantity INT,
  mrp_value NUMERIC(14,2),      -- qty × MRP
  nsv_value NUMERIC(14,2),      -- net sales value
  discount_value NUMERIC(14,2), -- mrp_value - nsv_value
  upload_batch_id BIGINT,       -- provenance / rollback
  PRIMARY KEY (brand_id, financial_year, sale_id)
)
PARTITION BY LIST (brand_id)          -- top level: isolate brands
  → SUBPARTITION BY RANGE (date)      -- by financial year (or month)
```
- **Natural/unique key** enforced by unique index on `(store_id, invoice_no, product_id)` (refine per Q6) → gives idempotent upserts and duplicate detection.
- `discount_pct` is **computed, not stored** (`100 − nsv/mrp×100`) to avoid drift — exposed via view.

### 4.3 Partitioning strategy
- **Level 1: LIST by `brand_id`.** Every brand-scoped query (almost all are) prunes to one partition. Re-upload of a brand's month touches only that brand's data. Brands grow independently.
- **Level 2: RANGE by financial year** (or month if a brand exceeds ~10M rows). YoY/season queries prune to relevant years; monthly re-upload = drop+reload one sub-partition = fast, clean idempotency.
- **BRIN index on `date`** within large partitions (cheap, great for range scans); **B-tree** on FK columns used in filters.

### 4.4 Indexing & filtering
Extensive filters (brand, color, article_type, discount range, store, category, subcategory, season, FY) resolve to **dimension keys**, so:
- Composite B-tree indexes on the fact's FK columns matching common filter combinations.
- Filters on textual attributes (color, article_type, category) hit **small dim tables** (indexed), then join to the fact by key — fast and cardinality-friendly.
- Discount-range filter uses the computed `discount_pct` — precomputed into the aggregate MVs by bucket so ranges are index-friendly.

### 4.5 Performance layer — how dashboards stay sub-second
1. **Materialized views** for every dashboard aggregate:
   - `mv_sales_summary` (brand × season × FY × month → total sales, MRP, NSV, discount).
   - `mv_store_perf` (brand × store × period → NSV, MRP, qty, discount%) → powers top-10 store + trends.
   - `mv_category_perf` (brand × category/subcategory × store × period → NSV, qty, discount%).
2. **Refresh strategy:** after each successful upload, the worker runs `REFRESH MATERIALIZED VIEW CONCURRENTLY` **only for the affected brand's views** (or targeted incremental recompute). MVs are read while refreshing (no downtime).
3. **Redis cache-aside:** dashboard endpoints hash the filter set → cache JSON result (TTL + explicit bust on upload of that brand). Repeat views are served from Redis in ms.
4. **Result:** raw `fact_sales` is essentially never scanned by the UI. Cold query hits an MV (thousands of rows); warm query hits Redis.

**Estimated performance impact:** dashboard endpoints < 150 ms cold (MV), < 20 ms warm (Redis); upload of a monthly file (tens of thousands of rows) processed + MV-refreshed in seconds to low minutes, fully async.

### 4.6 Ingestion pipeline (the crux)
```
Upload → store raw file in object storage (immutable)
       → create upload_batch (status=received)
       → worker: read Excel (pandas)
       → apply brand's column-mapping config (source col → canonical field, type coercion, value normalization)
       → VALIDATE: required fields, types, negative/zero rules, store/category resolves to a dim, key uniqueness
       → if errors: batch=failed, produce structured error report (row, column, reason) → shown in UI, file not loaded
       → if clean: load into staging → idempotent merge into fact (replace (brand,month) sub-partition per Q7)
       → REFRESH affected MVs → bust Redis → batch=completed (row counts, timings)
```
- **Per-brand mapping config** lives in `dim_brand.upload_config` (JSONB) editable via Django admin — new brand onboarding = add a config, **no code change**. This directly answers "every brand has its own format."
- **upload_batch** gives full provenance, progress, and one-click rollback (delete by batch_id).
- This same pipeline is the seed for the Phase-2 **data-impurity detection UI** (validation findings become fixable items instead of hard failures).

### 4.7 RBAC (extensible by design)
- Model: `User → Role → Permissions` on top of Django Groups/permissions.
- Phase 1 roles: **Super Admin** (everything, incl. brand/config/user admin), **Data Inserter** (upload + view). New roles (e.g., Brand Manager scoped to one brand, Read-Only Analyst) are data, not code.
- Note #4 "extensible" is satisfied because permissions are checked, not role names; adding a role = new Group + permission set + optional brand scoping.

### 4.8 SoH reconciliation design (Phase 2, specified now)
- Inputs: secondary-sales upload, dealer-stock (submitted SoH) upload, goods-return upload — each via the **same configurable ingestion pipeline**.
- `Calculated SoH = Σ secondary_sales − Σ tertiary_sales` (± returns) at brand & store grain.
- Compare to submitted SoH → status: **Green** (match), **Red** (calc < submitted), **Amber** (calc > submitted). Rendered as a reconciliation table (matches the doc's example table).
- Lives as its own analytics module + MVs; **no schema disruption** to Phase 1 because it reuses dims and the batch/ingestion machinery.

### 4.9 Recommendation engine hooks (Phase 2)
- Phase 1 deliberately produces the clean, dimensional, seasonal fact base these recommendations need. Targets: stores to focus, categories to push, inventory movement, sales opportunities; horizons monthly / quarterly / seasonal, **max 2 seasons ahead** (aligns with 6-month inventory planning).
- Approach when we get there: start with **transparent statistical baselines** (season-over-season growth, store/category momentum, ABC/velocity analysis) before any ML. Explainable, cheap, and often good enough; ML only if it beats the baseline measurably. No premature Spark/ML platform.

### 4.10 Does the HLD cover the client's use cases?
| Requirement (from doc/notes) | Covered by | Phase |
|---|---|---|
| Brand + Yearly/Monthly + Year/Month selection, Excel upload | Ingestion + master data + brand config | 1 |
| Dashboard: season select; Total/MRP/Net sales, Total discounts | `mv_sales_summary` + dashboard API | 1 |
| Store-wise: top-10 stores, brand/year/month filter | `mv_store_perf` | 1 |
| Category-wise: top-10, store multi-select, order by NSV/qty/discount% | `mv_category_perf` | 1 |
| Trends: store/category/subcategory YoY / MoM / SeasonBySeason | period-dimension queries over MVs | 1 |
| Extensive filtering (color, article type, discount range, …) | dim model + indexes + filter API | 1 |
| Roles: Super Admin, Data Inserter, extensible | RBAC module | 1 |
| Monthly incremental upload, sanitized, idempotent | ingestion + partition replace | 1 |
| Per-brand upload formats | JSONB mapping config | 1 |
| Invoice uniqueness = Store + Invoice No | unique index | 1 |
| Caching/indexing/partitioning/MV recommendations | performance layer | 1 |
| SoH: secondary/dealer-stock/returns upload, Calculated vs Submitted, RAG | SoH module | 2 |
| CN calculation | Phase-2 module (needs formula) | 2 |
| Data-impurity detect/display/fix in UI | extends validation stage | 2 |
| Recommendation engine (stores/categories/inventory/opportunities) | analytics-on-star | 2 |

---

## 5. Phasing

### Phase 1 (this 10–12 day sprint) — "Trustworthy sales analytics"
Auth + RBAC · master data + per-brand upload config · configurable Excel ingestion with validation & provenance · canonical partitioned star schema · Dashboard / Store-wise / Category-wise / Trends views · extensive filtering · MV + Redis performance layer · monthly idempotent incremental upload · Dockerized deploy + backups.

### Phase 2 — "Reconciliation + intelligence"
SoH reconciliation (secondary/dealer-stock/returns) with RAG · CN calculation · data-impurity detection & in-UI correction · recommendation engine (baseline stats first) · optional SSO/multi-tenant hardening.

---

## 6. Phase 1 — day-wise plan (deliverables + git commits)

Assumes 12 working days; if only 10, Days 10–11 compress and trend polish moves to buffer. Each day ends green (migrations run, tests pass, deployable).

**Day 0 (pre-work, ~½ day): confirm blocking clarifications (§1A).** Freeze canonical schema.

**Day 1 — Foundation & skeleton**
- Repo, Docker Compose (Postgres, Redis, Django, worker, nginx), settings/env, CI lint+test, pre-commit.
- Deliverable: `docker compose up` runs an empty API + DB + worker.
- Commits: `chore: scaffold compose + django project`, `ci: lint/test pipeline`, `feat: health endpoint`.

**Day 2 — Data model & migrations**
- `dim_brand/store/product/calendar`, `fact_sales` with LIST+RANGE partitioning, unique key, indexes; calendar/season/FY generator.
- Deliverable: migrations apply; seed script loads dims; partition auto-creation helper.
- Commits: `feat: dimensional schema + partitioned fact`, `feat: calendar/season generator`, `test: schema constraints`.

**Day 3 — Auth & RBAC**
- User model, JWT/session auth, Groups→permissions, Super Admin + Data Inserter, Django admin for master data.
- Deliverable: login, protected endpoints, role-gated access; admin manages brands/stores.
- Commits: `feat: auth + jwt`, `feat: extensible rbac roles`, `feat: admin for master data`.

**Day 4 — Brand upload config + ingestion skeleton**
- JSONB mapping-config model + admin UI; object-storage client; `upload_batch` model; upload endpoint stores raw file + enqueues job.
- Deliverable: upload a file → raw stored in R2/B2 → batch=received.
- Commits: `feat: brand column-mapping config`, `feat: raw upload + object storage`, `feat: upload_batch provenance`.

**Day 5 — Ingestion: parse + map + validate**
- Worker: pandas read → apply mapping → coerce types → validation rules → structured error report; failed vs clean paths.
- Deliverable: bad file → downloadable error report; clean file → validated staging rows.
- Commits: `feat: excel parse + mapping`, `feat: validation + error report`, `test: ingestion fixtures (2 brand formats)`.

**Day 6 — Ingestion: load + idempotency + MV refresh**
- Idempotent merge (replace (brand,month) sub-partition), affected-MV refresh, Redis bust, batch status/rollback.
- Deliverable: end-to-end upload → queryable facts; re-upload same month = no dupes.
- Commits: `feat: idempotent fact load`, `feat: mv refresh + cache bust`, `feat: batch rollback`.

**Day 7 — Materialized views + analytics read-path**
- `mv_sales_summary/store_perf/category_perf`; raw-SQL analytics service; cache-aside layer.
- Deliverable: dashboard summary + store-wise + category-wise APIs return correct numbers, cached.
- Commits: `feat: aggregate materialized views`, `feat: analytics read-path + redis cache`, `test: aggregate correctness`.

**Day 8 — Filtering + trends API**
- Unified filter param model (brand/store/category/subcategory/color/article_type/season/FY/month/discount-range); trends (YoY/MoM/SeasonBySeason) endpoints.
- Deliverable: every documented filter + top-10 orderings + trend series via API.
- Commits: `feat: composable filter engine`, `feat: trends yoy/mom/season`, `test: filter matrix`.

**Day 9 — Frontend shell + Dashboard view**
- React/Vite/AntD app, auth flow, layout, global filter bar; Dashboard (totals, MRP, NSV, discounts) with ECharts.
- Deliverable: usable dashboard against live API.
- Commits: `feat: react app shell + auth`, `feat: global filter bar`, `feat: dashboard view`.

**Day 10 — Store-wise & Category-wise views**
- Top-10 store table, category/subcategory tables with store multi-select + NSV/qty/discount% ordering; upload screen with progress + error-report download.
- Deliverable: all core analytical screens usable end-to-end.
- Commits: `feat: store-wise view`, `feat: category-wise view`, `feat: upload UI + status`.

**Day 11 — Trends UI, hardening, seed demo data**
- Trends charts; empty/error states; input validation; load-test with synthetic ~30M rows; index/MV tuning from real timings.
- Deliverable: full Phase-1 feature set; measured sub-second dashboards.
- Commits: `feat: trends UI`, `perf: index/mv tuning`, `test: load + e2e smoke`.

**Day 12 — Deploy, backups, docs, handover**
- Provision VPS, TLS (Caddy/nginx+certbot), nightly `pg_dump`→object storage, restore runbook, README/ops docs, seed admin.
- Deliverable: **production URL live**, backups verified, docs done.
- Commits: `chore: prod compose + tls`, `ops: automated backups + restore runbook`, `docs: architecture + ops handover`, `release: v1.0.0`.

**Buffer/risks:** Days 5–6 (ingestion) are the likeliest to slip because of real-world Excel messiness — the schedule front-loads them and keeps trend polish (Day 11) as the compressible item.

---

## 7. Monthly infrastructure cost (Phase 1)

Single-VPS Compose deployment (INR region available on most providers). Ranges reflect current provider pricing.

| Item | Spec | ~Monthly |
|---|---|---|
| VPS (app+DB+Redis+worker) | 4–8 vCPU / 8–16 GB / 160–240 GB SSD (e.g., Hetzner CPX/CCX class) | $20–40 |
| Object storage (raw uploads + backups) | tens of GB, low egress (Cloudflare R2 / Backblaze B2) | $1–5 |
| Domain / TLS | domain amortized; Let's Encrypt TLS free | ~$1 |
| Off-box backup storage | nightly pg_dump retention | included above |
| **Total (Phase 1)** | | **~$25–45 / month** |

**Contrast — full managed cloud (for reference, not recommended yet):** RDS Postgres + ElastiCache + ECS/Fargate + S3 + ALB ≈ **$150–350/month**. We move here only when uptime SLAs or scale justify it — the migration path in §3.8 keeps that door open at no rework cost.

> Note: provider prices shift (Hetzner adjusted prices in 2026). Treat the VPS figure as a current-market estimate to confirm at purchase.

---

## 8. Risk register (top items)

| Risk | Impact | Mitigation |
|---|---|---|
| Heterogeneous, messy Excel per brand | Ingestion slips, bad data | Config-driven mapping + strict validation + staging + immutable raw files + error reports; front-loaded in schedule |
| Wrong canonical grain/key | Rework of schema mid-sprint | Freeze via §1A blocking questions on Day 0 |
| Single-VPS availability | Downtime | Daily off-box backups + 30-min restore runbook; vertical headroom; managed-DB migration path ready |
| Scope creep (SoH/recommendations into Phase 1) | Foundation quality suffers | Hard phase boundary; SoH/CN/impurity/reco explicitly Phase 2 |
| MV refresh cost as data grows | Slow uploads | Per-brand targeted refresh + partition-scoped recompute; move to incremental/rollup if needed |
| Re-upload duplication | Corrupted metrics | Idempotent partition-replace + unique key + batch rollback |

---

## 9. What I'd change about the stated approach (honest pushback)

- **Don't build multi-tenant SaaS isolation now** unless you're actually selling to multiple companies (Q9). Single-tenant with brand-as-dimension is simpler and faster; the star schema already carves by brand, so upgrading later is contained.
- **Don't store category taxonomy inside each brand's file blindly.** Curating a mapped `dim_category` (Q8) is a few hours that makes every cross-brand filter and future recommendation dramatically cleaner. Worth it.
- **Resist adding a BI tool (Metabase/Superset) as "the dashboard."** It seems like a shortcut but fights you on the bespoke top-10/discount%/season UX and the RBAC model. A thin custom React layer over your own APIs is more work up front but the right long-term codebase. (Metabase is still worth wiring for *ad-hoc internal* exploration — just not as the product.)
- **Consider RQ over Celery** if you want fewer moving parts as a solo dev; you lose little.

---

*Prepared for review. Answer §1A (8 questions) and I'll freeze the schema and start Day 1.*
