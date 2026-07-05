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
ops/                docker-compose assets, nginx config, backup scripts, runbooks
docs/               architecture, plan, ADRs
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
