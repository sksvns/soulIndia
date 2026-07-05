# Canonical schema — frozen (Day 0)

This freezes the target schema from `plan.md` §3 against the two real seed
files (`KILLER - EAN CODE WISE SALE 23-24 TO 25-26.xlsb`,
`PEPE BIHAR DSR REPORT 2026.xlsb`). Machine-readable mapping configs are in
`docs/mapping-configs/*.json`; this document is the human-readable
column-by-column trace proving every source column lands somewhere.

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
- Confirmed empirically (not from a sample assumption): on every negative-`QTY SALE` row, `QTY SALE`, `NET SALE VALUE`, `DISCOUNT VALUE`, and `MRP SALE VALUE` are all negative together; `MRP` (unit price) stays positive. `is_return := quantity < 0` is sufficient.
- `NEW EAN CODE` and `EAN CODE` are identical in every sampled row.

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

## Open items still pending (not blocking Day 0)

- Explicit store-month deletion (no replacement data) — needs a client-defined
  workflow, not inferable from sample files. (Day 6)
- Zero-value / GWP rows — client to share examples; treated as a Phase 2
  data-quality concern unless told otherwise. (Day 5)
