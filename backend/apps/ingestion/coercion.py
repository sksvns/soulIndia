"""Per-field type coercion, dispatched by each canonical field's `cast`
(docs/schema.md, apps/masterdata/seed_data/*.json). Deliberately explicit
and per-field rather than relying on pandas' automatic dtype inference,
which would silently mangle real data we've already seen: barcodes read as
floats (8905646747185.0), jeans sizes mixed between "S"/"M"/"L" strings and
32.0/34.0 floats, mixed-type invoice numbers, and Excel dates stored as raw
serial numbers by some engines (pyxlsb) but as datetimes by others
(openpyxl).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd

EXCEL_EPOCH = date(1899, 12, 30)


class CoercionError(Exception):
    pass


def is_blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def to_str(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def to_barcode(value) -> str:
    if isinstance(value, float):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def to_excel_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return EXCEL_EPOCH + timedelta(days=float(value))
    if isinstance(value, str):
        stripped = value.strip()
        try:
            # CSV has no native date type -- a serial number arrives as
            # plain text (e.g. "45017"), unlike Excel engines which return
            # int/float directly. Try that reading before falling back to
            # a real calendar-date string.
            return EXCEL_EPOCH + timedelta(days=float(stripped))
        except ValueError:
            pass
        parsed = pd.to_datetime(stripped, errors="coerce")
        if pd.isna(parsed):
            raise CoercionError(f"unparseable date: {value!r}")
        return parsed.date()
    raise CoercionError(f"unparseable date: {value!r}")


def to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise CoercionError(f"not a decimal number: {value!r}") from exc


def to_int(value) -> int:
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:
        raise CoercionError(f"not a number: {value!r}") from exc
    if not as_float.is_integer():
        raise CoercionError(f"expected a whole number, got {value!r}")
    return int(as_float)


def fraction_to_percent(value) -> Decimal:
    # Deliberately not to_decimal(value) * 100 -- that would quantize to 2
    # decimal places of the raw 0-1 fraction *before* scaling, throwing away
    # exactly the precision needed once expressed as a percentage.
    try:
        raw = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CoercionError(f"not a decimal number: {value!r}") from exc
    return (raw * 100).quantize(Decimal("0.01"))


CASTERS = {
    "str": to_str,
    "barcode": to_barcode,
    "excel_serial_date": to_excel_date,
    "decimal": to_decimal,
    "int": to_int,
    "fraction_to_percent": fraction_to_percent,
}


def normalize_dimension_text(value: str) -> str:
    """Light normalization for filter/grouping consistency (category, color,
    size, etc). Never applied to month/season/financial_year, which the
    frozen rule requires to be trusted exactly as supplied.
    """
    return value.strip().upper()
