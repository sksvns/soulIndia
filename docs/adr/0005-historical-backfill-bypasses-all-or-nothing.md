# ADR-0005: Historical backfill is a separate, Super-Admin-only path that loads good rows and reports bad ones

**Status:** Accepted
**Date:** 2026-07-06

## Context

Day 5's ingestion rule is deliberately all-or-nothing: any row error fails
the whole file, nothing loads. That guarantee is correct for routine
monthly uploads -- a client should fix and resubmit a clean file, not have
the system silently guess at bad rows.

Loading a brand's actual historical export for the first time (plan.md Day
12: "load real historical files per brand") is a different situation. The
real files have years of real data-quality debt already baked in --
confirmed loading the complete real Killer file: 11,760 of 748,161 rows
(1.6%) had genuine issues (blank `discount_value`, literal text `"NA"` in
`unit_mrp`, missing product identity). Blocking the *entire* historical
load on every one of those being perfect first would withhold revenue
history the client already has elsewhere, for an indefinite correction
cycle, with no way to make partial progress in the meantime.

The user asked directly for this capability ("load all killer good data and
create a csv of bad data with reason"). Before building it, the user was
asked explicitly whether this should become the standard behavior for every
upload, or a separate one-time path -- they chose the latter.

## Decision

1. `apps/ingestion/backfill.py` is a parallel module to `pipeline.py`: same
   Phase A parse/map/validate (`parse_map_validate`, shared by both), but
   rows that pass are loaded and rows that don't are reported in a CSV,
   instead of the whole file failing on any single error. Nothing is ever
   silently dropped -- every rejected row is in the CSV with its exact
   field/value/reason, same shape as the regular path's error report.
2. Two ways to invoke it, both calling the same `execute_backfill(batch)`
   orchestration so there is exactly one implementation of the "load good,
   report bad" behavior:
   - `manage.py backfill_historical <brand> <product_line> <file> --user-email=...`
     (synchronous, CLI-driven, for direct ops use).
   - `POST /api/ingestion/backfill/` (async via Celery, same request shape
     and same status-polling as the regular `/uploads/` endpoint).
3. The regular `POST /api/ingestion/uploads/` endpoint and
   `pipeline.run_pipeline` are **completely unchanged** -- still strictly
   all-or-nothing. Nothing about routine monthly uploads/corrections is
   affected by this decision.
4. `POST /api/ingestion/backfill/` requires `ingestion.alter_existing_data`
   (the same permission ADR-0003 introduced for altering already-loaded
   data) -- Super Admin only, not available to Data Inserter. Bypassing the
   all-or-nothing data-quality gate is treated as at least as sensitive as
   altering existing data, not a routine action.
5. `GET /api/ingestion/uploads/<id>/error-report/` downloads a batch's
   error CSV directly. This isn't backfill-specific -- it also fixes a
   pre-existing gap in the regular upload path, which already stored
   `error_report_key` but had no way to fetch it via the API.
6. A backfill batch that touches a `(store, month)` slice that already has
   data still goes through `loader.load_batch`'s existing ADR-0003 gate
   unchanged -- backfill does not bypass that check, only the all-or-nothing
   file-level gate.

## Alternatives considered

- **Make partial-load the default behavior for every upload** -- rejected
  after asking the user directly; would permanently weaken the all-or-
  nothing guarantee for routine corrections, where "fix and resubmit a
  clean file" is the correct, simpler client workflow.
- **One combined endpoint with an `?allow_partial=true` flag** instead of a
  separate `/backfill/` path -- rejected in favor of a clearly separate,
  distinctly-permissioned URL: a flag on the same endpoint makes it easy to
  accidentally invoke the weaker guarantee from client code that meant to
  call the strict one.

## Consequences

- `pipeline.py` was refactored to expose `parse_map_validate` (parse + map
  + coerce + validate, no DB writes, no gate) so both `run_pipeline` and
  `run_backfill_pipeline` share it rather than duplicating Phase A.
- Backfilling the complete real Killer file for the first time is what
  surfaced the two real sign patterns in ADR-0004 -- a large real dataset
  exercises the pipeline in ways smaller verified samples don't.
