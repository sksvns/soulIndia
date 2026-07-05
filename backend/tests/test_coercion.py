from datetime import date, datetime
from decimal import Decimal

import pytest

from apps.ingestion import coercion


def test_is_blank():
    assert coercion.is_blank(None)
    assert coercion.is_blank("")
    assert coercion.is_blank("   ")
    assert coercion.is_blank(float("nan"))
    assert not coercion.is_blank(0)
    assert not coercion.is_blank("0")
    assert not coercion.is_blank("x")


def test_to_str_collapses_whole_number_floats_to_avoid_trailing_dot_zero():
    assert coercion.to_str(32.0) == "32"
    assert coercion.to_str("  M  ") == "M"
    assert coercion.to_str(6045) == "6045"


def test_to_barcode_handles_float_and_scientific_and_dotzero_text():
    assert coercion.to_barcode(8905646747185.0) == "8905646747185"
    assert coercion.to_barcode("8905646747185.0") == "8905646747185"
    assert coercion.to_barcode("8905646747185") == "8905646747185"


def test_to_excel_date_from_python_date_and_datetime():
    assert coercion.to_excel_date(date(2023, 4, 5)) == date(2023, 4, 5)
    assert coercion.to_excel_date(datetime(2023, 4, 5, 10, 30)) == date(2023, 4, 5)


def test_to_excel_date_from_raw_serial_number():
    # 45017 is 2023-04-01 -- confirmed against the real Killer file (Day 0).
    assert coercion.to_excel_date(45017) == date(2023, 4, 1)
    assert coercion.to_excel_date(45017.0) == date(2023, 4, 1)


def test_to_excel_date_from_numeric_string_serial():
    # CSV has no native date type -- a serial arrives as plain text.
    assert coercion.to_excel_date("45017") == date(2023, 4, 1)


def test_to_excel_date_from_calendar_date_string():
    assert coercion.to_excel_date("2023-04-05") == date(2023, 4, 5)


def test_to_excel_date_rejects_garbage():
    with pytest.raises(coercion.CoercionError):
        coercion.to_excel_date("not-a-date")


def test_to_decimal_quantizes_to_two_places():
    assert coercion.to_decimal(1399) == Decimal("1399.00")
    assert coercion.to_decimal("2124.5") == Decimal("2124.50")
    assert coercion.to_decimal(2099.03) == Decimal("2099.03")


def test_to_decimal_rejects_garbage():
    with pytest.raises(coercion.CoercionError):
        coercion.to_decimal("not-a-number")


def test_to_int_accepts_whole_number_floats():
    assert coercion.to_int(1.0) == 1
    assert coercion.to_int("32") == 32


def test_to_int_rejects_fractional_values():
    with pytest.raises(coercion.CoercionError):
        coercion.to_int(1.5)


def test_fraction_to_percent():
    assert coercion.fraction_to_percent(0.4001057444984281) == Decimal("40.01")


def test_normalize_dimension_text():
    assert coercion.normalize_dimension_text("  shirts  ") == "SHIRTS"
    assert coercion.normalize_dimension_text("Light Blue") == "LIGHT BLUE"
