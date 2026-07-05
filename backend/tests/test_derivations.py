import pytest

from apps.ingestion.derivations import (
    DerivationError,
    apply_derived_fields,
    financial_year_from_month_text,
)


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
