# ADR-0002: No natural key on `fact_sales`; correction unit is (brand, store, month)

**Status:** Accepted
**Date:** 2026-07-05

## Context

Sales rows arrive as per-brand Excel/CSV exports. Inspection of the two real
seed files (`KILLER - EAN CODE WISE SALE 23-24 TO 25-26.xlsb`,
`PEPE BIHAR DSR REPORT 2026.xlsb`) confirms line-item grain with **no reliable
unique key**: duplicate lines (identical store/date/article/size/invoice) are
legitimate — e.g. two identical rows for invoice `PRHO26-79842`, barcode
`8905875293132` appear back-to-back in the real Pepe extract, differing in
nothing. A composite unique index on `(store, invoice_no, article, size)` would
reject one of them and silently drop real sales.

Corrections arrive as a full re-export of a store's data for a period, not a
diff. The client corrects one store at a time (a store's till was
misreported), not the whole brand.

## Decision

1. `fact_sales.sale_id` is a surrogate `BIGINT GENERATED` primary key. No
   business-column uniqueness is enforced on the fact table.
2. A **non-unique** index on `(store_id, invoice_no, product_id)` exists for
   query performance and duplicate *reporting*, not duplicate *prevention*.
3. Idempotency and corrections are handled by **slice replace**, not
   row-level upsert: for every `(brand, store, month)` combination present in
   an upload, the load transaction deletes existing `fact_sales` rows for that
   exact slice, then inserts the new rows — tagged with `upload_batch_id` and
   `source_row_no` for provenance and one-shot rollback (`DELETE WHERE
   upload_batch_id = :id`).
4. Slices not present in an upload are left untouched. Re-uploading Store A's
   April file only ever touches Store A's April rows; Store B and every other
   month are unaffected.

## Confirmed by real data during Day 0

- **Return-row sign consistency (previously an open item) — confirmed
  empirically, no client input needed.** Scanning the full 748k-row Killer
  file and the Pepe DSR extract: on every negative-quantity row, `quantity`,
  `mrp_value` (line total), `net_value`, and `discount_value` are **all
  negative together**; the unit price column (`MRP`) itself stays positive.
  `is_return := quantity < 0` is a reliable, sufficient derivation for both
  brands.
- **Single vs. multi-month files (previously an open item) — the real Pepe
  file itself spans 4 months** (`JANUARY-2026` … `APRIL-2026`, ~16k rows) in
  one export. **The loader must not assume one file = one month.** Slice
  detection groups rows by `(store_code, month)` actually present in the
  parsed frame, independent of file name or count. This is now a hard
  requirement, not a nice-to-have, and is reflected in the Day 6 design.

## Alternatives considered (and rejected)

- **Composite unique key + upsert** — rejected; real data has legitimate
  duplicate lines, so any unique constraint on business columns would reject
  valid rows.
- **Whole-brand replace per upload** — rejected; corrections are
  store-specific per the client's workflow, so replacing an entire brand on
  every correction would blow away unrelated stores' correct data for no
  reason and multiply load time.
- **Diff/merge against previous upload** — rejected; adds real complexity
  (row matching with no reliable key) for a case (partial corrections within
  a store-month) the client hasn't asked for. Slice replace is simpler and
  matches how the client actually re-exports data (full store-month dumps).

## Consequences

- `upload_batch.slices` (JSONB) records exactly which `(store, month)` pairs
  a batch touched — this is what the Day 6 loader iterates over, what
  targets materialized-view refresh, and what a rollback undoes.
- No natural-key validation step is needed in the Day 5 validation engine;
  duplicate lines are not flagged as errors.
- Still open, deferred to Day 6 (needs client input, not inferable from the
  sample files): how an operator signals "delete this store-month entirely,
  with no replacement data" — normal upload only ever *replaces* slices that
  are present in the file, so an explicit removal action is a distinct,
  separate operation to be designed then.
