"""Phase A: pure validation over already-coerced canonical rows -- no DB
writes. If this fails, nothing downstream runs (dimension resolution is
Phase B and only starts once every row here passes; see ADR-0002 for why
"nothing loaded" must include not creating orphan dim_store/dim_product
rows from a batch that ultimately fails).

Zero-quantity and zero-MRP rows are rejected here as Phase 1 data-quality
issues (the open "zero-value/GWP rows" item from the brief) rather than
silently accepted -- revisit once the client shares real GWP examples.

Deliberately NOT checked: mrp_value == unit_mrp * quantity. Verified against
a genuine 1000-row slice of the real Killer file (not just hand-built
fixtures) and it fails on ~7% of real, legitimate rows -- MRP SALE VALUE
sometimes reflects a different reference basis than the current MRP column
(most likely EOSS/scheme pricing). This was never a frozen requirement, just
an inference from the plan's "compute mrp_value" wording; real data overrode
it. mrp_value/net_value/discount_value are trusted as directly supplied.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class IngestionError:
    row_no: int
    field: str
    value: Any
    reason: str


def validate_rows(
    canonical_rows: list[dict], column_map: dict, validation_rules: dict
) -> list[IngestionError]:
    errors: list[IngestionError] = []
    required_fields = validation_rules.get("required_canonical_fields", list(column_map.keys()))
    tolerance_pct = float(validation_rules.get("discount_pct_tolerance_pct", 2.0))

    for row in canonical_rows:
        row_no = row["_row_no"]

        for field, message in row.get("_coercion_errors", {}).items():
            errors.append(IngestionError(row_no, field, None, message))

        for field in required_fields:
            if row.get(field) in (None, ""):
                errors.append(IngestionError(row_no, field, None, "required field is missing"))

        quantity = row.get("quantity")
        unit_mrp = row.get("unit_mrp")
        mrp_value = row.get("mrp_value")
        net_value = row.get("net_value")

        if quantity == 0:
            errors.append(
                IngestionError(
                    row_no,
                    "quantity",
                    quantity,
                    "zero quantity is not supported in Phase 1 (possible GWP/data-quality row)",
                )
            )
        if unit_mrp == 0:
            errors.append(
                IngestionError(
                    row_no,
                    "unit_mrp",
                    unit_mrp,
                    "zero MRP is not supported in Phase 1 (possible GWP/data-quality row)",
                )
            )

        # discount_value (= mrp_value - net_value) is deliberately excluded
        # from this check: verified against the real Pepe file, a sale can
        # legitimately have net_value > mrp_value (a markup/premium, or
        # paisa-level rounding noise), which makes discount_value negative
        # on an otherwise perfectly normal sale row. Only quantity, mrp_value,
        # and net_value need to agree on sign (confirmed empirically, Day 0).
        if quantity is not None and None not in (mrp_value, net_value):
            is_return = quantity < 0
            for label, value in (
                ("mrp_value", mrp_value),
                ("net_value", net_value),
            ):
                if is_return and value > 0:
                    errors.append(
                        IngestionError(
                            row_no,
                            label,
                            value,
                            "positive value on a return row (quantity < 0); expected non-positive",
                        )
                    )
                if not is_return and value < 0:
                    errors.append(
                        IngestionError(
                            row_no,
                            label,
                            value,
                            "negative value on a sale row (quantity > 0); expected non-negative",
                        )
                    )

        if mrp_value and net_value is not None:
            computed_discount_pct = (1 - (net_value / mrp_value)) * 100
            supplied_pct = row.get("supplied_discount_pct")
            if (
                supplied_pct is not None
                and abs(computed_discount_pct - supplied_pct) > tolerance_pct
            ):
                errors.append(
                    IngestionError(
                        row_no,
                        "supplied_discount_pct",
                        supplied_pct,
                        f"supplied discount% differs from computed ({computed_discount_pct:.2f}%) "
                        f"by more than {tolerance_pct}%",
                    )
                )

    return errors
