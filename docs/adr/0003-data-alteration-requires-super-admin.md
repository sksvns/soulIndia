# ADR-0003: Altering already-loaded sales data requires Super Admin, and is always audited

**Status:** Accepted
**Date:** 2026-07-05

## Context

Day 6 shipped idempotent store-month replace: any upload whose file touches
a `(store, month)` slice that already has `fact_sales` rows deletes and
replaces that slice. This is correct and desired for genuine corrections,
but as originally built it was available to any user with upload access
(Data Inserter), with no distinction between "loading new data" and
"replacing/removing data that's already in the system" -- and no durable
record of which happened, by whom.

The user raised this directly while reviewing Day 6: replacing or removing
existing data is materially more sensitive than adding new data, and should
require elevated access, with every attempt -- allowed or blocked --
recorded for later review.

## Decision

1. A new Django permission, `ingestion.alter_existing_data`, gates two
   actions: replacing an existing `(store, month)` slice (during load) and
   rolling back a loaded batch. Both are checked against the *uploading*
   user (the batch's `uploaded_by`) or the *acting* user (whoever invokes
   rollback), never against `request.user` implicitly -- consistent with
   the existing capability-based RBAC (`user.has_perm(...)`, never a
   role-name check).
2. Super Admin has it automatically, because `seed_roles` already gives
   Super Admin *every* permission that exists (self-updating on each new
   migration). Data Inserter does not, because it isn't added to that
   role's curated allowlist. No new role-name branching anywhere in the
   code.
3. A fresh load into slices with no existing data is never gated and never
   audited -- only genuine alterations are. Day-to-day monthly uploads by
   Data Inserter stay exactly as fast and unblocked as before.
4. Every alteration attempt -- whether it proceeds or is blocked -- creates
   a permanent `DataAlterationAudit` row (user, brand, action, affected
   slices/row counts, allowed/blocked, timestamp), visible read-only in
   Django admin. A blocked attempt raises `DataAlterationNotPermitted` with
   the message "You are altering data that requires Super Admin access
   (N affected item(s))", surfaced to the uploader via `UploadBatch.
   failure_reason` (now included in the API response -- it wasn't, which
   was a real gap caught while building this).
5. This is treated as an expected, clean rejection (like a Day 5 validation
   failure), not a system error: the Celery task catches it specifically
   and does *not* re-raise, unlike a genuine unexpected failure.

## Alternatives considered

- **Hardcode a role-name check (`if user.groups.filter(name="Super
  Admin").exists()`)** -- rejected; contradicts the established
  capability-based RBAC design and would need a code change for any future
  role that should also get this capability (e.g. a "Regional Admin" in
  Phase 2). The permission-based approach needs only a group-permission
  change.
- **Silently drop or skip conflicting rows instead of blocking the whole
  batch** -- rejected outright; the user was explicit that no record should
  ever be silently altered or lost. Blocking with a clear, actionable error
  is the only acceptable behavior for an unauthorized alteration attempt.
- **Log to text/stdout only, no dedicated audit table** -- rejected as
  insufficient for something the user wants to be able to review later;
  `DataAlterationAudit` is queryable and visible in Django admin, not just
  buried in log lines (though it's also logged, at INFO for allowed and
  WARNING for blocked, for real-time operational visibility).

## Consequences

- Rollback's function signature changed (`rollback_batch(batch, user)`);
  the Django admin action passes `request.user`.
- Added general-purpose structured logging (Django `LOGGING` config,
  stdout, Docker-captured) as part of the same piece of work -- this was a
  real gap (only one file had any logging before today). True *monitoring*
  (uptime alerts, error-tracking dashboards e.g. Sentry) is deliberately
  deferred to Day 12/Phase 2 -- it needs an external service, which is
  outside the frozen Phase 1 stack and wasn't a decision to make silently
  mid-feature.

**2026-07-18 update -- Delete Data page.** The client asked for a Delete
Data page (select brand + product line + financial year + month, preview,
one confirmation dialog, delete). This is the exact same alteration this
ADR already governs, extended to a filter-based selection instead of a
single batch -- `delete_by_filter` (`apps/ingestion/loader.py`) reuses
`_audit_and_require_permission` unchanged and is gated by the same
`ingestion.alter_existing_data` permission. Two consequences of that
selection being a filter, not one batch:

- `DataAlterationAudit.batch` is now nullable -- a filter delete can span
  every batch that ever loaded into that (brand, product_line, financial
  year, month) slice, so there's no single batch to attribute it to; the
  filter criteria and affected row count live in `details` instead.
- `preview_delete` and `delete_by_filter` share one `_deletable_queryset`
  helper so the confirmation dialog's preview and the actual delete can
  never drift apart -- what the admin is shown is exactly what gets
  removed.

Also fixed while building this: `rollback_batch` deleted fact rows but
never called `refresh_all()`/`analytics_cache.bust()` afterward, unlike the
load path -- dashboards would have kept showing rolled-back data until an
unrelated refresh. Both `rollback_batch` and `delete_by_filter` now do
both, only when rows were actually deleted.
