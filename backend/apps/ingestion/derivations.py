"""Derived-field exceptions to "never derive, always trust as supplied" --
Pepe's financial_year (docs/schema.md, confirmed 2026-07-05) and Kraus's
unit_mrp (confirmed 2026-07-18: Kraus's source file has no per-unit MRP
column at all, only a line-total MRP and quantity). A new derived field
is a deliberate, reviewed code addition here, not a config-only change:
unlike ordinary column routing, a derivation is a business rule about how
to compute a value, not just where to find it. Dispatch is by canonical
field name -- each derivable field has exactly one derivation rule, never
several competing ones a config would need to pick between.
"""

import re
from decimal import Decimal

MONTH_NAME_TO_NUMBER = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

MONTH_YEAR_RE = re.compile(r"([A-Za-z]+)\s*-?\s*(\d{4})")


class DerivationError(Exception):
    pass


def financial_year_from_month_text(month_text: str) -> str:
    """'JANUARY- 2026' -> '25-26' (Apr-Mar FY, matching Killer's supplied
    string format so both brands' financial_year values are directly
    comparable in filters/trends)."""
    match = MONTH_YEAR_RE.search(month_text.upper())
    if not match:
        raise DerivationError(f"cannot parse month/year from {month_text!r}")
    month_name, year_str = match.group(1), match.group(2)
    month_no = MONTH_NAME_TO_NUMBER.get(month_name)
    if month_no is None:
        raise DerivationError(f"unrecognized month name in {month_text!r}")
    year = int(year_str)
    start_year = year if month_no >= 4 else year - 1
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def unit_mrp_from_mrp_and_quantity(row: dict) -> Decimal | None:
    """Kraus has no per-unit MRP column in its source file, only a line-
    total MRP and quantity (confirmed 2026-07-18) -- unit_mrp = mrp_value
    / quantity, the field's literal meaning, with no other source to
    trust instead. abs() handles return rows (quantity and mrp_value both
    negative; the per-unit price itself is still positive)."""
    mrp_value = row.get("mrp_value")
    quantity = row.get("quantity")
    if mrp_value is None or not quantity:
        return None
    return abs(mrp_value / quantity)


def apply_derived_fields(canonical_row: dict, validation_rules: dict) -> dict:
    """Fills in any field declared under validation_rules.derived_fields that
    the brand didn't supply directly. Mutates and returns canonical_row."""
    for field_name, spec in validation_rules.get("derived_fields", {}).items():
        if canonical_row.get(field_name):
            continue  # brand actually supplied it; never override

        if field_name == "unit_mrp":
            canonical_row[field_name] = unit_mrp_from_mrp_and_quantity(canonical_row)
            continue

        source_field = spec.get("derived_from", "").lower()
        source_value = canonical_row.get(source_field)
        if not source_value:
            continue  # surfaces as a missing-required-field error downstream
        try:
            canonical_row[field_name] = financial_year_from_month_text(source_value)
        except DerivationError:
            canonical_row[field_name] = None
    return canonical_row
