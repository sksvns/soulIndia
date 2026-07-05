from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import PEPE_BAD_ROWS, PEPE_GOOD_ROWS, pepe_workbook


@pytest.fixture
def pepe_brand_and_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="PEPE")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.mark.django_db
def test_pepe_good_file_validates_100_percent_with_correct_sanity_check_math(
    pepe_brand_and_config,
):
    brand, config = pepe_brand_and_config
    workbook = pepe_workbook(PEPE_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_dsr.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3

    sanity_row = next(r for r in result.rows if r["invoice_no"] == "PRHO26-79718")
    assert sanity_row["unit_mrp"] == Decimal("2999.00")
    assert sanity_row["mrp_value"] == Decimal("2999.00")
    assert sanity_row["net_value"] == Decimal("1799.00")
    assert sanity_row["discount_value"] == Decimal("1200.00")
    computed_discount_pct = (1 - sanity_row["net_value"] / sanity_row["mrp_value"]) * 100
    assert round(computed_discount_pct) == 40
    assert sanity_row["supplied_discount_pct"] == Decimal("40.00")  # WAD 0.40 -> 40%

    return_row = next(r for r in result.rows if r["invoice_no"] == "0101N-019614")
    assert return_row["is_return"] is True
    assert return_row["unit_mrp"] == Decimal("3499.00")  # unit price stays positive


@pytest.mark.django_db
def test_pepe_financial_year_is_correctly_derived_per_row_since_pepe_supplies_none(
    pepe_brand_and_config,
):
    brand, config = pepe_brand_and_config
    workbook = pepe_workbook(PEPE_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_dsr.xlsx")

    assert result.ok, result.errors
    january_row = next(r for r in result.rows if r["invoice_no"] == "PRHO26-79718")
    april_row = next(r for r in result.rows if r["invoice_no"] == "PRHON26-8583")
    assert january_row["financial_year"] == "25-26"
    assert april_row["financial_year"] == "26-27"


@pytest.mark.django_db
def test_pepe_good_file_resolves_dimensions_with_the_2_level_category_hierarchy(
    pepe_brand_and_config,
):
    brand, config = pepe_brand_and_config
    workbook = pepe_workbook(PEPE_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_dsr.xlsx")

    assert result.ok
    assert DimStore.objects.filter(brand=brand, store_code="SI-032").exists()
    product = DimProduct.objects.get(brand=brand, barcode="8905875293118")
    assert product.category == "TOP WEAR"  # GEN-CAT -> category
    assert product.sub_category == "SHIRTS"  # CATEGORY -> sub_category


@pytest.mark.django_db
def test_pepe_bad_file_fails_with_precise_actionable_errors(pepe_brand_and_config):
    brand, config = pepe_brand_and_config
    workbook = pepe_workbook(PEPE_BAD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_bad.xlsx")

    assert not result.ok
    by_row = {}
    for error in result.errors:
        by_row.setdefault(error.row_no, []).append(error)

    assert any(e.field == "barcode" and "missing" in e.reason for e in by_row[1])
    assert any(e.field == "quantity" and "zero quantity" in e.reason for e in by_row[2])
    assert any(
        e.field == "supplied_discount_pct" and "differs from computed" in e.reason
        for e in by_row[3]
    )


@pytest.mark.django_db
def test_pepe_single_file_spanning_multiple_months_validates_each_row_independently(
    pepe_brand_and_config,
):
    """Confirms Day 5 doesn't assume one file = one month (ADR-0002) -- every
    row validates on its own regardless of which month it belongs to. Slice
    detection/replace across months is Day 6's job."""
    brand, config = pepe_brand_and_config
    workbook = pepe_workbook(PEPE_GOOD_ROWS)  # spans January and April 2026

    result = run_pipeline(brand, config, workbook, "pepe_dsr.xlsx")

    assert result.ok
    months = {r["month"] for r in result.rows}
    assert months == {"JANUARY- 2026", "APRIL- 2026"}
