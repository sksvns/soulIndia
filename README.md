# Retail Analytics Platform

Multi-brand apparel/footwear tertiary-sales analytics. See `docs/plan.md` for
the day-by-day delivery plan, `docs/architecture.md` for the engineering
rationale, `docs/schema.md` for the frozen canonical schema, and `docs/adr/`
for architecture decision records.

## Run it locally

```bash
cp .env.example .env
docker compose up --build
```

- Frontend (via nginx): http://localhost
- Backend API directly: http://localhost:8000
- Health check: http://localhost/health/ (checks Postgres, Redis, and the
  Celery broker)
- Django admin: http://localhost/admin/

The `backend` (gunicorn) container auto-reloads on code changes. The
`celery` worker does not -- restart it after changing any `apps.ingestion`
task/pipeline code, or a stale worker process will keep running old logic:
`docker compose restart celery`.

## Repository layout

```
backend/            Django project (apps: accounts, masterdata, ingestion, analytics)
frontend/           React + Vite + Ant Design + ECharts
ops/                Caddy config, backup/restore + deploy runbooks
docs/               architecture, plan, ADRs, load-test results
.github/workflows/  CI (lint + test + frontend build)
```

## Backend tests & lint

```bash
docker compose exec backend pytest -q
docker compose exec backend ruff check .
docker compose exec backend black --check .
```

## Frontend

```bash
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

## Production deployment

`docker compose up --build` (above) auto-loads `docker-compose.override.yml`
for dev conveniences (host ports on every service, bind-mounted source,
the Vite dev server). Production explicitly skips that file and layers
`docker-compose.prod.yml` instead -- a static frontend build, tuned
gunicorn workers, restart policies, and Caddy for reverse proxy +
automatic Let's Encrypt TLS, with no internal service (Postgres, Redis,
MinIO) exposed to the host:

```bash
cp .env.prod.example .env   # fill in every REPLACE_ME placeholder
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

See `ops/runbooks/deploy.md` for the full first-deploy checklist
(domain/DNS prerequisites, seeding the initial Super Admin, redeploys)
and `ops/runbooks/restore.md` for how nightly backups work and the
step-by-step disaster-recovery restore procedure (backed by a real,
timed restore drill against this project's full ~36.8M-row dataset).
