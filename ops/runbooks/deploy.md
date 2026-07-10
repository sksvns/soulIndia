# Production deploy runbook

Status: artifacts are prepared and verified locally (see "What's been
verified" below); an actual public VPS/domain has not been provisioned
in this engagement yet. This is the checklist for when one is.

## Prerequisites

- A VPS reachable on ports 80 and 443 (2 vCPU / 4 GB RAM is a reasonable
  starting point at Phase-1 scale; see `docs/load-test.md` for the
  numbers this was sized against).
- A domain name with an A (and AAAA, if using IPv6) record pointed at the
  VPS's IP address -- Caddy cannot obtain a Let's Encrypt certificate
  without this resolving correctly first.
- Docker + the Docker Compose plugin installed on the VPS.

## First deploy

1. Clone the repo onto the VPS and check out the release tag:
   ```bash
   git clone <repo-url> soulIndia && cd soulIndia
   git checkout v1.0.0
   ```
2. Copy the prod env template and fill in every `REPLACE_ME` placeholder
   (`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `OBJECT_STORAGE_*`
   credentials, and `DOMAIN`/`DJANGO_ALLOWED_HOSTS`/
   `DJANGO_CSRF_TRUSTED_ORIGINS` with the real domain):
   ```bash
   cp .env.prod.example .env
   # generate a real secret key:
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
3. Bring the stack up. This explicitly skips
   `docker-compose.override.yml` (the dev-only file) by only passing the
   base + prod files:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
4. Watch Caddy obtain its certificate:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy
   ```
   Look for `certificate obtained successfully` for your real domain
   (not `"issuer":"local"` -- that means it fell back to Caddy's internal
   CA, which only happens when the domain doesn't resolve publicly yet).
5. Seed the initial Super Admin (see `ops/runbooks/restore.md`'s
   "Seeding the initial Super Admin" section):
   ```bash
   docker compose exec backend python manage.py create_super_admin \
     --email=you@yourcompany.com --password='<a real generated password>'
   ```
6. **A fresh database has zero master data** -- migrations create the
   schema, not the brand/upload-config/calendar rows the Upload page
   depends on (its Brand and Product Line selects populate from
   `/api/masterdata/upload-configs/`; both stay empty and the Upload
   button stays disabled until this runs). Learned the hard way on the
   first real deploy: seed it before anyone tries to upload a file.
   ```bash
   docker compose exec backend python manage.py seed_calendar
   docker compose exec backend python manage.py seed_brands
   docker compose exec backend python manage.py seed_upload_configs
   docker compose exec backend python manage.py seed_attribute_registry
   ```
   All four are idempotent -- safe to re-run. `fact_sales` partitions for
   whatever financial year a file covers are created automatically by
   the upload pipeline itself (`ensure_partition_for_date` in
   `apps/ingestion/loader.py`), not a separate manual step.
7. Historical brand data: **only "already loaded" if you restored an
   existing backup** (`ops/runbooks/restore.md`) rather than migrating a
   fresh database forward -- a fresh database has no fact rows either,
   same as it has no master data. Upload real historical files through
   the normal Upload page, or use the Super-Admin-only
   `backfill_historical` management command (ADR-0005), same as it does
   today.
8. Set up the nightly backup cron job on the host (see
   `ops/runbooks/restore.md`'s "Scheduling" section).
9. Confirm the app is reachable end-to-end: log in at `https://<your
   domain>/`, view a dashboard with real data, and confirm
   `https://<your domain>/health/` reports every dependency `ok`.

## What's been verified (without a real domain yet)

The exact `docker-compose.prod.yml` + `ops/caddy/Caddyfile` in this repo
were brought up live in an isolated test (`DOMAIN=localhost`, so Caddy's
automatic-HTTPS fell back to its internal CA instead of Let's Encrypt --
the same code path, just a different certificate issuer) and confirmed
working over real HTTPS: the built frontend SPA and its client-side
routing, `/health/` and Django admin proxied correctly to gunicorn,
Django admin's static assets served from the `collectstatic` output, and
automatic HTTP->HTTPS redirects. See the `chore: prod compose + tls`
commit for details. What's *not* yet verified is the one part that
requires a real public domain: an actual Let's Encrypt certificate
issuance and renewal cycle.

## Redeploying (after a code change)

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Compose recreates only the services whose image/config changed; Caddy
and the database keep running undisturbed (their volumes, and Caddy's
already-issued certificate, persist across this).

## Scaling gunicorn workers

`GUNICORN_WORKERS` in `.env` (default 4). A reasonable starting formula
is `(2 x CPU cores) + 1`; watch `docker compose logs backend` under real
load and adjust.
