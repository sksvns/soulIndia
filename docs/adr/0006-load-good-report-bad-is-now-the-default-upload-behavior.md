# ADR-0006: Load-good-report-bad is now the default upload behavior, reversing ADR-0005's scoping decision

**Status:** Accepted
**Date:** 2026-07-11

## Context

ADR-0005 built the "load good rows, report bad rows in a CSV" behavior
specifically for one-time historical backfill, and deliberately kept the
regular `POST /api/ingestion/uploads/` endpoint (used by the actual
Upload page) strictly all-or-nothing: any single bad row rejected the
entire file, loading nothing. That was an explicit choice at the time --
the user was asked directly whether partial-load should become the
standard behavior for every upload or stay a separate one-time path, and
chose the latter.

In practice, after the platform went live, this produced the opposite of
the intended experience: a Data Inserter uploading a real file with even
one bad row (out of possibly thousands of good ones) got the whole file
rejected with no rows loaded, no matter how clean the rest of the file
was. Fixing a single bad row and re-uploading a large real file, just to
get every other row loaded too, is a worse day-to-day workflow than the
one ADR-0005 built for exactly this reason.

## Decision

1. `apps.ingestion.tasks.process_upload_batch` -- the Celery task behind
   the regular `/uploads/` endpoint -- now calls the same
   `apps.ingestion.backfill.execute_backfill` orchestration the backfill
   path already used, instead of the old all-or-nothing `run_pipeline`
   gate. Every upload now loads whatever rows pass validation and reports
   the rest in a CSV, available to any Data Inserter, not just Super
   Admin.
2. `pipeline.run_pipeline` (the all-or-nothing gate itself) is **not**
   deleted -- it's still correct, still tested directly by the
   pipeline-level test suite (`test_pipeline_killer.py` and friends,
   which exercise Phase A/B mechanics unrelated to this specific
   all-or-nothing-vs-partial question), and remains a reasonable building
   block. It's just no longer what any HTTP endpoint's Celery task calls.
3. `POST /api/ingestion/backfill/` still exists, still requires
   `ingestion.alter_existing_data` (Super Admin) per ADR-0003/0005, and is
   now **behaviorally identical** to the regular endpoint -- kept as a
   distinct URL for anything already calling it directly (the
   `backfill_historical` CLI command calls `execute_backfill` directly,
   independent of this view) rather than removed outright. Its original
   protective purpose -- restricting who could bypass the all-or-nothing
   gate -- is moot now that the gate doesn't exist on the regular path
   either; this is a known, accepted consequence, not an oversight.
4. ADR-0003's actual data-alteration protection (Super Admin required to
   replace an existing `(store, month)` slice, or to roll back a batch)
   is completely unaffected -- that check lives inside `loader.load_batch`
   itself, independent of which pipeline path calls it, and still applies
   identically to every upload regardless of this change.
5. The Upload page's UI needed no changes at all: it already displayed
   `row_count` and `error_count` independently of batch status (built
   during ADR-0005, since a backfill batch could already be `LOADED` with
   `error_count > 0`), so a regular upload landing in that same state
   displays correctly with zero frontend work.

## Alternatives considered

- **Add a toggle/flag on the Upload page instead of changing the default**
  -- rejected; ADR-0005 already rejected a flag-based single endpoint for
  the risk of accidentally invoking the weaker guarantee from client code
  that meant to call the strict one. Now that partial-load is the *only*
  behavior for every upload, that risk doesn't exist to guard against.
- **Remove `/backfill/` and `backfill_historical` since they're now
  redundant** -- rejected as out of scope for this change; nothing asked
  for their removal, and they still work correctly. A future decision to
  simplify by removing them can be made separately and explicitly.

## Consequences

- `apps/ingestion/tasks.py` lost its `_run()` helper and the separate
  `process_backfill_batch` task -- both endpoints now enqueue the same
  `process_upload_batch` task.
- Tests updated: `test_ingestion_tasks.py` gained a mixed-good-and-bad-rows
  test through the regular endpoint (mirroring the equivalent backfill
  test) and had its system-error patch target updated; `test_backfill_
  endpoint.py` updated its task references to the merged task name. No
  existing all-bad-file test needed behavior changes, since "zero valid
  rows" still means `FAILED` under the new logic too.
