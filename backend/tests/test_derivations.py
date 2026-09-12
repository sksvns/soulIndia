import pytest

from apps.ingestion.derivations import (
    DerivationError,
    apply_derived_fields,
    apply_store_identity_overrides,
    financial_year_from_month_text,
)

KRAUS_OVERRIDES = {
    "KRA-1": "PANKH",
    "KRA-2": "DAFTARI TEXTILES PVT LTD",
    "KRA-3": "THE BOMBAY FASHION",
}


def test_financial_year_from_month_text_jan_to_mar_belongs_to_prior_calendar_year():
    assert financial_year_from_month_text("JANUARY- 2026") == "25-26"
    assert financial_year_from_month_text("FEBRUARY- 2026") == "25-26"
    assert financial_year_from_month_text("MARCH- 2026") == "25-26"


def test_financial_year_from_month_text_apr_to_dec_starts_that_calendar_year():
    assert financial_year_from_month_text("APRIL- 2026") == "26-27"
    assert financial_year_from_month_text("DECEMBER- 2026") == "26-27"


def test_financial_year_from_month_text_rejects_garbage():
    with pytest.raises(DerivationError):
        financial_year_from_month_text("not a month at all")


def test_apply_derived_fields_fills_missing_financial_year_for_pepe():
    validation_rules = {
        "derived_fields": {"financial_year": {"derived_from": "MONTH"}},
    }
    row = {"month": "JANUARY- 2026"}

    result = apply_derived_fields(row, validation_rules)

    assert result["financial_year"] == "25-26"


def test_apply_derived_fields_never_overrides_a_directly_supplied_value():
    validation_rules = {
        "derived_fields": {"financial_year": {"derived_from": "MONTH"}},
    }
    row = {"month": "JANUARY- 2026", "financial_year": "23-24"}

    result = apply_derived_fields(row, validation_rules)

    assert result["financial_year"] == "23-24"


def test_apply_derived_fields_is_a_noop_without_a_derived_fields_section():
    row = {"month": "JANUARY- 2026"}

    result = apply_derived_fields(row, validation_rules={})

    assert "financial_year" not in result


def test_store_identity_overrides_leaves_a_correctly_shaped_row_untouched():
    """The original Kraus file shape: STORE CODE already holds the real
    KRA-x code, STORE NAME already holds the real name."""
    row = {"store_code": "KRA-1", "store_name": "PANKH"}

    result = apply_store_identity_overrides(row, {"store_identity_overrides": KRAUS_OVERRIDES})

    assert result == {"store_code": "KRA-1", "store_name": "PANKH"}


def test_store_identity_overrides_corrects_a_swapped_row():
    """A later Kraus export shape: STORE NAME holds the KRA-x code, STORE
    CODE holds an unrelated per-row reference number -- must be corrected
    to the real (code, name) pair, discarding the reference number."""
    row = {"store_code": "0202-0016039", "store_name": "KRA-3"}

    result = apply_store_identity_overrides(row, {"store_identity_overrides": KRAUS_OVERRIDES})

    assert result["store_code"] == "KRA-3"
    assert result["store_name"] == "THE BOMBAY FASHION"


def test_store_identity_overrides_is_a_noop_for_a_row_matching_neither_side():
    row = {"store_code": "SOME-OTHER-CODE", "store_name": "SOME OTHER STORE"}

    result = apply_store_identity_overrides(row, {"store_identity_overrides": KRAUS_OVERRIDES})

    assert result == {"store_code": "SOME-OTHER-CODE", "store_name": "SOME OTHER STORE"}


def test_store_identity_overrides_is_a_noop_without_the_config_key():
    row = {"store_code": "0202-0016039", "store_name": "KRA-3"}

    result = apply_store_identity_overrides(row, validation_rules={})

    assert result == {"store_code": "0202-0016039", "store_name": "KRA-3"}
