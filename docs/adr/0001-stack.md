# ADR-0001: Backend/data stack for Phase 1

**Status:** Accepted
**Date:** 2026-07-05

## Context

One developer must ship Phase 1 (auth/RBAC, configurable multi-brand ingestion, a
partitioned star schema, four analytics views with extensive filtering, and a
performance layer) in ~10–12 working days, at low infra cost, with a clean
migration path as data grows ~5x. Full rationale, alternatives, and sizing
analysis are in [`../architecture.md`](../architecture.md) §2–3; this ADR
records the decision itself.

## Decision

| Layer | Choice |
|---|---|
| Database | PostgreSQL 16 (declarative partitioning, materialized views, JSONB) |
| Cache / broker | Redis 7 |
| Backend | Python 3.12, Django 5 + Django REST Framework |
| Background jobs | Celery + Redis |
| Ingestion | pandas + openpyxl/pyxlsb, bulk load via `COPY` |
| Frontend | React 18 + Vite + Ant Design + ECharts |
| Object storage | S3-compatible (Cloudflare R2 / Backblaze B2; MinIO in dev) |
| Deploy | Docker Compose on a single VPS; nginx (static + reverse proxy); TLS via Caddy/certbot |
| CI | GitHub Actions: lint + test on every push |

A modular monolith (one deployable backend, clean internal module boundaries:
`accounts` / `masterdata` / `ingestion` / `analytics`), not microservices.

## Alternatives considered (and rejected for Phase 1)

- **ClickHouse / Kafka / Spark** — unjustified below ~100M+ rows with genuinely
  ad-hoc scans; we never scan raw `fact_sales` from the UI (materialized views
  do that job). Second system to operate, for no benefit at this scale.
- **FastAPI + SQLAlchemy + Alembic** — better fit for a thin async API, but
  would cost 2–3 days hand-building auth, RBAC, and an admin UI that Django
  gives for free. Reconsider only if async I/O becomes a measured bottleneck.
- **Kubernetes** — no operational benefit at this scale; pure ops overhead for
  a solo dev.
- **Managed cloud (RDS/ElastiCache/ECS)** — ~$150–350/mo vs. ~$25–45/mo for
  Compose-on-VPS; deferred until uptime SLA or scale demands it.

## Consequences

- Analytics read-path is raw SQL over materialized views (never the ORM, never
  raw `fact_sales`), so it can be lifted into a separate read-service later
  with zero data-model change.
- Django's sync model is fine here because dashboards are cache/MV-served and
  uploads are async via Celery — no user-facing request does heavy synchronous
  I/O.
- Single-VPS deploy is a single point of failure, deliberately accepted for
  cost; mitigated by nightly off-box backups and a tested restore runbook
  (Day 12).

## Migration path

Compose → managed Postgres (DSN swap) → containers to ECS/Cloud Run → read
replica → (only if ever needed) a columnar read replica via CDC for one heavy
view. Nothing in Phase 1 blocks any of these.
