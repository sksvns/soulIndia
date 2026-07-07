# ADR-0004: Two additional real sign patterns are accepted, not rejected, by validation

**Status:** Accepted
**Date:** 2026-07-06

## Context

Day 5's sign-consistency rule (`quantity`, `mrp_value`, `net_value` must all
agree in sign) was verified against a 10,000-row slice of the real Killer
file and the complete real Pepe file, and held in both. Backfilling the
*complete* 748,161-row Killer file for the first time (see
`apps/ingestion/backfill.py`) surfaced two real patterns that sample never
happened to contain, together responsible for 201 of that run's rejected
rows:

- **Pattern A:** a return recorded with `quantity` left **positive** --
  `mrp_value`/`net_value` going negative (with `discount_value = 0`) is what
  actually signals the return, not the quantity sign.
- **Pattern B:** a normal **sale** where a flat scheme/coupon discount
  (observed: a flat ₹2000 discount applied to items priced well under that)
  exceeds the item's `mrp_value`, driving `net_value` negative while
  `mrp_value` itself stays positive.

Both were confirmed against the actual raw rows (not inferred) before any
rule change, and both were presented to the user with concrete examples
before deciding how to handle them.

## Decision

1. `is_return := quantity < 0 OR mrp_value < 0`. Money sign is
   authoritative when it disagrees with quantity in this specific direction
   (positive quantity, negative money) -- accepted as Pattern A.
2. `net_value`'s sign is no longer checked against the return/sale
   classification **at all**, on either branch -- only `quantity` and
   `mrp_value` need to agree. This accepts Pattern B (`mrp_value > 0`,
   `net_value < 0`) and is symmetric with Day 5's existing exclusion of
   `discount_value`'s sign from the same check, for the same underlying
   reason: real discount/markup arithmetic can legitimately push `net_value`
   in either direction relative to `mrp_value`.
3. The one sign combination with **no** legitimate real-data match found
   across the complete file: negative `quantity` with positive `mrp_value`.
   This remains a validation error ("positive value on a return row").
4. `pipeline.py`'s `is_return` assignment (used for `fact_sales.is_return`,
   independent of the validation check) was updated to match the same rule.

## Alternatives considered

- **Keep the stricter Day 5 rule and reject both patterns as bad data** --
  rejected: both are real, legitimate business transactions confirmed
  against actual raw data, not data-entry errors. Rejecting them would
  silently exclude genuine revenue/return history from the historical
  backfill for no correctness benefit.
- **Silently coerce Pattern A's quantity to negative to "fix" the
  convention** -- rejected; the row is stored and classified as a return via
  `is_return`, but the raw `quantity` value is never altered, matching the
  general "trusted as directly supplied" rule for fact fields.

## Consequences

- `KILLER_BAD_ROWS` in `tests/ingestion_fixtures.py` changed: its
  "sign mismatch" case is now negative-quantity + positive-`mrp_value`
  (the one combination still rejected), not positive-quantity +
  negative-`net_value` (now accepted, per Pattern B).
- New fixture rows and tests (`test_pipeline_killer.py`) cover both accepted
  patterns explicitly, asserting `is_return` classification and that the
  rows load without error.
- Discovered specifically *because* `apps/ingestion/backfill.py` (see
  ADR-0005) made loading the complete real file for the first time
  practical -- a reminder that sample-based verification, however large,
  doesn't substitute for eventually running the real, complete dataset
  through the pipeline.
