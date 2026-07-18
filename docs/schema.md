# Canonical schema — frozen (Day 0)

This freezes the target schema from `plan.md` §3 against the two real seed
files (`KILLER - EAN CODE WISE SALE 23-24 TO 25-26.xlsb`,
`PEPE BIHAR DSR REPORT 2026.xlsb`). Machine-readable mapping configs (loaded
by `seed_upload_configs`, Day 4) live in
`backend/apps/masterdata/seed_data/*.json` -- moved there from an initial
`docs/mapping-configs/` draft location once Day 4 needed them inside the
Docker build context to actually load them. This document is the
human-readable column-by-column trace proving every source column lands
somewhere.

**Rule with no exceptions:** every source column maps to either a canonical
field or `extra` JSONB. Nothing is ever silently dropped — there is no
"ignore" bucket. New/unrecognized columns in a future file default to `extra`
automatically (this is what makes onboarding womenswear/kids/footwear later
non-breaking).

## Dimensions (unchanged from plan.md §3)

- `dim_brand(brand_id, brand_code, brand_name, active, created_at)`
- `brand_upload_config(config_id, brand_id, product_line, name, column_map JSONB, date_source, validation_rules JSONB, active)`
- `dim_store(store_id, brand_id, store_code, store_name, city, state, zone, store_type, distributor_name, extra JSONB)` — `UNIQUE(brand_id, store_code)`
- `dim_product(product_id, brand_id, barcode, article_code, item_name, main_category, category, sub_category, gender, fit, color, size, print_type, extra JSONB)` — `UNIQUE(brand_id, barcode)`
- `dim_calendar(date_id, date, day, month_no, month_name, quarter, financial_year)`
- `dim_season(season_id, season_code, season_type, season_year, sort_order)`
- `attribute_registry(attr_id, canonical_name, source, is_filterable, is_dimension, data_type, active)`

## Fact (unchanged from plan.md §3)

`fact_sales(sale_id BIGINT GENERATED, brand_id, store_id, product_id, date_id, season_id, invoice_no, quantity, unit_mrp, mrp_value, net_value, discount_value, is_return, extra JSONB, upload_batch_id, source_row_no, created_at)`, `PARTITION BY LIST(brand_id)` → `RANGE(sale_date)` per FY. See ADR-0002 for why there's no natural key.

## Killer (menswear) — 34 source columns, all accounted for

date_source = `NEW DATE`. Source: `23-24 TO 25-26 SALE REPORT` sheet, 748,161 data rows.

| # | Source column (as it appears in file) | Canonical target |
|---|---|---|
| 1 | INVOICE DATE | `extra` (secondary date; NEW DATE is authoritative) |
| 2 | NEW DATE | `sale_date` (authoritative) |
| 3 | MONTH | `month` (trusted as supplied) |
| 4 | BILL NO / INVOICE NO | `invoice_no` |
| 5 | PARTY NAME (AS PER STORE SIGNAGE) | `extra` (near-duplicate of NAME) |
| 6 | NAME | `store_name` |
| 7 | STORE CODE | `store_code` |
| 8 | BRAND | `extra` (redundant with upload context) |
| 9 | REPORT STATUS | `extra` |
| 10 | STORE STATUS | `extra` |
| 11 | TYPE | `store_type` (see note below) |
| 12 | ZONE | `zone` |
| 13 | CITY | `city` |
| 14 | STATE | `state` |
| 15 | DISTRIBUTOR NAME NEW | `distributor_name` |
| 16 | ASM / RSM | `extra` |
| 17 | EAN CODE | `barcode` fallback source |
| 18 | NEW EAN CODE | `barcode` primary source |
| 19 | MAIN CATEGORY | `category` |
| 20 | ITEM NAME | `article_code` |
| 21 | CATEGORY | `sub_category` |
| 22 | SHADE | `color` |
| 23 | SIZE | `size` |
| 24 | SEASON | `season` (trusted as supplied) |
| 25 | MRP | `unit_mrp` |
| 26 | FIT | `fit` |
| 27 | PRINT TYPE | `print_type` |
| 28 | CLSNG QTY | `extra` (Phase 2 SoH) |
| 29 | CLSNG VALUE | `extra` (Phase 2 SoH) |
| 30 | QTY SALE | `quantity` |
| 31 | NET SALE VALUE | `net_value` |
| 32 | DISCOUNT VALUE | `discount_value` |
| 33 | MRP SALE VALUE | `mrp_value` |
| 34 | F. YEAR | `financial_year` (trusted as supplied) |

**Observations from real data (Day 0):**
- Scanned all 748,161 rows: `TYPE` is constant `"SALE"` throughout this file. It's mapped to `store_type` per the client's column mapping, but currently carries no discriminative information — flagged for re-verification once a file shows a different value.
- Confirmed empirically against a 10,000-row sample (not the full file): on every negative-`QTY SALE` row, `QTY SALE`, `NET SALE VALUE`, `DISCOUNT VALUE`, and `MRP SALE VALUE` are all negative together; `MRP` (unit price) stays positive. `is_return := quantity < 0` looked sufficient at this sample size.
- `NEW EAN CODE` and `EAN CODE` are identical in every sampled row.

**Correction after backfilling the complete 748,161-row file** (not just the
10k sample): a second real return convention exists —
`QTY SALE` stays **positive** while `MRP SALE VALUE`/`NET SALE VALUE` go
negative (`DISCOUNT VALUE` typically `0`). Confirmed as a genuine return, not
bad data, and accepted by explicit product decision:
`is_return := quantity < 0 OR mrp_value < 0`. A second, unrelated pattern
also only surfaced at full scale: a flat scheme/coupon discount can exceed a
cheap item's `MRP SALE VALUE`, driving `NET SALE VALUE` negative on an
otherwise completely normal **sale** (`MRP SALE VALUE` stays positive) — also
accepted, not flagged as an error. The one sign combination with no
legitimate real-data match across the full file: negative quantity with
positive `MRP SALE VALUE`. See `apps/ingestion/validation.py` and
`docs/adr/` for the reasoning; this is a case of a larger real dataset
surfacing genuine business patterns a smaller sample didn't happen to
contain, not a sample that was wrong.

## Pepe (menswear) — 28 source columns, all accounted for

date_source = `DATE`. Source: `PEPE DSR- 2026` sheet, 16,373 data rows spanning January–April 2026.

| # | Source column | Canonical target |
|---|---|---|
| 1 | Store Name | `store_name` |
| 2 | CITY | `city` |
| 3 | STORE CODE | `store_code` |
| 4 | L2L / ANULIZED | `extra` |
| 5 | Counter Types | `extra` |
| 6 | BA Name | `extra` |
| 7 | MONTH | `month` (trusted as supplied) + source for derived `financial_year` (see below) |
| 8 | QUARTERS | `quarter` (trusted as supplied) |
| 9 | DATE | `sale_date` (authoritative) |
| 10 | BillNo | `invoice_no` |
| 11 | STOCKNo | `barcode` |
| 12 | PC9 | `article_code` |
| 13 | Size | `size` |
| 14 | MRP | `unit_mrp` |
| 15 | Units | `quantity` |
| 16 | Total MRP | `mrp_value` |
| 17 | Net Sale Price | `net_value` |
| 18 | Actual Disc | `discount_value` |
| 19 | WAD | `supplied_discount_pct` (validate only; stored as a fraction, ×100 before comparing) |
| 20 | GENDER | `gender` |
| 21 | GEN - CAT | `category` |
| 22 | CATEGORY | `sub_category` |
| 23 | FIT | `fit` |
| 24 | COLOR | `color` |
| 25 | SEASON | `season` (trusted as supplied) |
| 26 | WEARHOUSE | `extra` |
| 27 | ATV-GWP-EOSS-Fresh | `extra` |
| 28 | Remarks (Offer/Fresh) | `extra` |

**`financial_year` for Pepe — documented exception:** Pepe's file has no FY
column at all. Confirmed with the product owner on 2026-07-05: derive FY from
`MONTH` for Pepe only (not from `DATE`, and not for any other brand — every
other brand's supplied FY is trusted as-is per the frozen rule). Real `MONTH`
values are formatted `"<MONTH NAME>- <YYYY>"` (e.g. `"JANUARY- 2026"`), which
already contains a year, so no fallback to `DATE` is needed. FY is computed
Apr–Mar and rendered in the same `YY-YY+1` string style Killer supplies (e.g.
`"25-26"`), so both brands' `financial_year` values are directly comparable in
filters/trends despite one being derived and one supplied.

**Observations from real data (Day 0):**
- Confirmed empirically: on every negative-`Units` row, `Units`, `Total MRP`,
  `Net Sale Price`, and `Actual Disc` are all negative together; `MRP` (unit
  price) stays positive — same pattern as Killer.
- Confirmed empirically: this single real file spans 4 months in one upload.
  Per ADR-0002, slice detection must group by `(store, month)` actually
  present in the data, not assume one file = one month.
- `BillNo` is mixed-type (mostly text, occasionally a bare number) → always
  cast to string. `STOCKNo` (barcode) is stored as a float in the source
  `.xlsb` → cast via `int()` before `str()` to avoid scientific notation.
- Sample sanity check (must hold in Day 7 tests): MRP 2999, Net 1799 →
  discount_value 1200, computed discount% = 40% (matches supplied WAD).

## Junior Killer (kids) — 33 source columns, all accounted for

date_source = `NEW DATE`. Source: `Sheet1` of the file (sheets are
`['Sheet2', 'Sheet1']` -- the data sheet is *not* index 0, same class of
gotcha as Killer's `SUMMARY` sheet), 39,389 data rows spanning Mar 2024 to
May 2026. Onboarded as a genuinely distinct brand (own `DimBrand` row, own
`(brand, product_line)` config) despite the near-identical column layout to
Killer's menswear file -- confirmed by `BRAND` being literally `"JR KILLER"`
in every row and store codes living in their own `JKESIS###` namespace,
distinct from Killer's `ESIS###` (store codes are unique only *within* a
brand, per the frozen decision). `product_line = "kids"`, matching the
frozen decision's anticipated womenswear/kids/footwear expansion -- the
first real instance of it.

| # | Source column | Canonical target |
|---|---|---|
| 1 | INVOICE DATE | `extra` (secondary date; NEW DATE is authoritative) |
| 2 | NEW DATE | `sale_date` (authoritative) |
| 3 | MONTH | `month` (trusted as supplied) |
| 4 | BILL NO / INVOICE NO | `invoice_no` |
| 5 | NAME AS PER REPORT RECEIVED | `extra` (near-duplicate of NAME, same role as Killer's PARTY NAME column) |
| 6 | NAME | `store_name` |
| 7 | STORE CODE | `store_code` |
| 8 | BRAND | `extra` (redundant with upload context; literally "JR KILLER" always) |
| 9 | REPORT STATUS | `extra` |
| 10 | STORE STATUS | `extra` |
| 11 | TYPE | `store_type` |
| 12 | ZONE | `zone` |
| 13 | CITY | `city` |
| 14 | STATE | `state` |
| 15 | DISTRIBUTOR NAME | `distributor_name` (Killer's equivalent column is named "DISTRIBUTOR NAME NEW" -- different exact header, same role, hence a separate config rather than sharing Killer's) |
| 16 | ASM / RSM | `extra` |
| 17 | EAN CODE | `barcode` fallback source |
| 18 | NEW EAN CODE | `barcode` primary source |
| 19 | MAIN CATEGORY | `category` |
| 20 | ITEM NAME | `article_code` |
| 21 | CATEGORY | `sub_category` |
| 22 | SHADE | `color` |
| 23 | SIZE | `size` (values like "11-12 YEARS" -- kids sizing, not adult) |
| 24 | SEASON | `season` (trusted as supplied) |
| 25 | MRP | `unit_mrp` |
| 26 | FIT | `fit` |
| 27 | PRINT TYPE | `print_type` |
| 28 | CLSNG QTY | `extra` (Phase 2 SoH) |
| 29 | CLSNG VALUE | `extra` (Phase 2 SoH) |
| 30 | QTY SALE | `quantity` |
| 31 | NET SALE VALUE | `net_value` |
| 32 | DISCOUNT VALUE | `discount_value` |
| 33 | MRP SALE VALUE | `mrp_value` |

**No `F. YEAR` column at all** (unlike Killer) -- `financial_year` is simply
unmapped for this brand. Not a problem: it isn't in
`required_canonical_fields`, and the analytics MVs derive `financial_year`
from `dim_calendar` via `sale_date` for every brand, never from this raw
supplied column (which only ever lands in `extra` for audit).

**Backfilled via `apps/ingestion/backfill.py` (ADR-0005), not the regular
upload path**, as the first real load of this brand's history: 38,545 of
39,389 rows loaded (97.9%); 844 rejected, 801 of them the same
"`discount_value` blank instead of `0`" pattern already seen in both other
real files, confirming it's a genuine cross-brand client-side export habit,
not a bug specific to one file.

## Kraus (womenswear) — 19 source columns, all accounted for

date_source = `Transaction Date`. Source: `Kraus Sales.xlsx`, a single
unnamed sheet (`Sheet1`), 63 sample rows, one store ("The Bombay Fashion" /
location `02`) -- confirmed 2026-07-18. Unlike Killer/Pepe/Junior Killer,
this file shares **no column vocabulary at all** with the other three
brands' exports; the mapping below was built from scratch by inspecting the
actual sample file, not a client-supplied mapping document. No `sheet_name`
is configured in `validation_rules` (unlike the other three) -- the real
file's one sheet is unnamed, so the pipeline's default (sheet index 0)
already does the right thing.

| # | Source column | Canonical target |
|---|---|---|
| 1 | Retailer | `store_name` |
| 2 | Transaction Type | `extra` (`"Retail Sales"` in every sampled row; no other value observed yet) |
| 3 | Supplier Name | `extra` (redundant with upload context, `"SOUL INDIA (PEPE)"` in every sampled row) |
| 4 | Transaction Location Id | `store_code` |
| 5 | Transaction Date | `sale_date` (real calendar-date string, e.g. `"21-Jun-2026"` -- not an Excel serial number; `to_excel_date`'s pandas fallback already handles this) |
| 6 | Transaction No | `invoice_no` |
| 7 | Brand Name | `extra` (redundant with upload context, always `"KRAUS"`) |
| 8 | Article No | `category` (only 4 distinct values in the sample -- L TOP/L TROUSER/L DENIM/L CARGO PANT, clearly a garment type despite the column's name, not a per-SKU code; client-confirmed 2026-07-18) |
| 9 | Size Name | `size` (combined format, e.g. `"26 / S"`, occasionally `"S / W-86CM"` with no consistent delimiter/order -- stored as-is, not split) |
| 10 | Style Name | `article_code` (the real per-SKU code, e.g. `LTA-2338`) |
| 11 | Eoss Scheme Name | `extra` (a promo-scheme label, e.g. `"B1-30,B2-40,KRAUS"` -- not an actual fashion season; client-confirmed 2026-07-18 not to map it to `season`) |
| 12 | Item Code w/o Batch | `barcode` |
| 13 | Total Discount Pct | `supplied_discount_pct` (validate-only; already a plain percentage like Killer/Junior Killer, unlike Pepe's WAD fraction) |
| 14 | Bill Discount Amt | `extra` (audit; always 0 in the sample) |
| 15 | Item Discount Amt | `extra` (audit) |
| 16 | Total Discount Amt | `discount_value` (bill+item combined; identical to Item Discount Amt in the sample since Bill is always 0, but Total is the field actually documented as the combined figure) |
| 17 | Transaction Quantity | `quantity` |
| 18 | Transaction Value at MRP | `mrp_value` |
| 19 | Transaction Value with GST | `net_value` |

**No `sub_category`-equivalent column at all** -- left unmapped, same
handling as any brand that doesn't supply an optional dimension.

**`unit_mrp` has no source column** -- derived as `mrp_value / quantity`
(`apps/ingestion/derivations.py::unit_mrp_from_mrp_and_quantity`), the one
other derived field besides Pepe's `financial_year`. `abs()` keeps the
per-unit price positive on return rows even though `mrp_value`/`quantity`
are both negative there.

This is a small (63-row), single-store sample, not a multi-month/multi-store
historical export like the other three brands' original samples -- the
mapping above (especially the return-row sign convention and the `unit_mrp`
derivation) should be re-verified once a larger real file is available.

## Pepe Kids (kids) — same 28-column template as Pepe menswear

No real Pepe Kids file inspected yet -- client-confirmed 2026-07-18 the
export format is identical to Pepe menswear's, so this config is a direct
copy of `pepe_menswear.json`'s `column_map`/`validation_rules` (same
column vocabulary, same `financial_year`-from-`MONTH` derivation, same
`WAD`-is-a-fraction handling). See Pepe's section above for the full
column-by-column trace -- it applies unchanged here.

**Onboarded as a genuinely distinct brand** (own `DimBrand` row, own
`(brand, product_line)` config), not a second `product_line` under the
existing `PEPE` brand: client-confirmed 2026-07-18 that a store selling
both Pepe menswear and Pepe Kids uses a *different* store code for the
Kids side, same convention as Killer vs Junior Killer. `product_line =
"kids"`.

Every column-mapping assumption here is inherited from Pepe menswear, not
independently confirmed -- treat this as provisional until a real Pepe
Kids file is uploaded and can reveal whether the header vocabulary,
`financial_year` derivation, or `WAD` fraction convention actually hold.

## Day 2 implementation notes

Two small, deliberate refinements surfaced while actually building the
migrations (both proven by tests, not just asserted):

- **`fact_sales` primary key is `(brand_id, sale_date, sale_id)`, not just
  `(brand_id, sale_id)`.** `fact_sales` is partitioned two levels deep --
  `LIST(brand_id)`, then each brand partition is further `RANGE(sale_date)`
  by financial year. PostgreSQL requires a partitioned table's unique
  indexes/PK to include the partition key of *every* partitioning level it
  will inherit down to, not just the top one. This was caught by
  `test_creating_a_brand_auto_creates_its_partition` failing against a real
  Postgres 16 instance with `NotSupportedError: unique constraint on
  partitioned table must include all partitioning columns`, not by
  inspection. `sale_id` is still the single globally-unique surrogate key
  (one shared sequence across all partitions, and what Django's ORM treats
  as the primary key) -- this is purely about what the physical composite
  constraint has to contain. No change to ADR-0002's guarantee: still no
  natural/business-column uniqueness anywhere on this table.
- **`dim_product` has `category` and `sub_category` only** -- no separate
  `main_category` or `item_name` columns, despite plan.md Sec 3's literal
  field list mentioning both. This matches the frozen 2-level category
  hierarchy decision (Category -> Sub-Category) and the Day 0 mapping
  configs already built against the real files, where `MAIN CATEGORY`/`ITEM
  NAME` land on `category`/`article_code` -- adding separate fields for them
  would just duplicate the same source data under redundant names for both
  real brands.

## Day 5 implementation notes

Verified the whole parse/map/validate pipeline against genuine slices of the
real files (10,000 Killer rows, the complete 16,373-row Pepe file) -- not
just hand-built fixtures. Three real findings changed the implementation,
each caught by an actual validation failure against real data, not by
inspection or guesswork:

- **`mrp_value == unit_mrp * quantity` does not hold universally and was
  removed as a validation rule.** ~7% of a real Killer sample failed it --
  "MRP Sale Value" sometimes reflects a different reference basis than the
  current MRP column (most likely EOSS/scheme pricing). This was never a
  frozen requirement, just an inference from the plan's "compute mrp_value"
  wording; `mrp_value`/`net_value`/`discount_value` are trusted as directly
  supplied, matching the frozen decision that discount% is always computed
  from them, never the reverse.
- **`discount_value`'s sign is excluded from the return/sale sign-consistency
  check.** `discount_value = mrp_value - net_value`, and a sale can
  legitimately have `net_value > mrp_value` (a markup/premium, or paisa-level
  rounding noise seen repeatedly in the real Pepe file, e.g. net exceeding
  mrp by exactly 0.01) -- which makes discount_value negative on an
  otherwise perfectly normal row. Only `quantity`, `mrp_value`, and
  `net_value` are required to agree on sign (the original Day 0 empirical
  finding), not `discount_value`.
- **Barcode fallback (`NEW EAN CODE` -> `EAN CODE`) needed to be a per-row
  decision, not a per-file one.** The real Killer file has rows where
  `NEW EAN CODE` is blank but the legacy `EAN CODE` column still has a
  value on that exact row. The initial implementation picked one winning
  header per canonical field for the whole file; `column_resolver` now
  returns every present candidate in priority order, and `row_mapper` picks
  the first non-blank one per row.

After these three fixes, the remaining validation failures against the real
data are all genuine, rare data-quality issues, not pipeline bugs: ~6 rows
per 10,000 with no MRP recorded at all (no fallback source exists), and
about 1 row per 1,000-1,500 where quantity's sign is inverted relative to
the value fields (net/mrp positive on a nominally-negative-quantity row, or
vice versa) -- an isolated data-entry error in the source system, correctly
rejected rather than silently miscounted as a sale or a return.

## Open items still pending (not blocking Day 0)

- Explicit store-month deletion (no replacement data) — needs a client-defined
  workflow, not inferable from sample files. (Day 6)
- Zero-value / GWP rows — client to share examples; treated as a Phase 2
  data-quality concern unless told otherwise. (Day 5)
