from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import (
    PEPE_GOOD_ROWS,
    PEPE_KIDS_BAD_ROWS,
    PEPE_KIDS_GOOD_ROWS,
    pepe_kids_workbook,
    pepe_workbook,
)


@pytest.fixture
def pepe_kids_brand_and_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="PEPE_KIDS")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.mark.django_db
def test_pepe_kids_good_file_validates_100_percent_with_correct_sanity_check_math(
    pepe_kids_brand_and_config,
):
    brand, config = pepe_kids_brand_and_config
    workbook = pepe_kids_workbook(PEPE_KIDS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_kids_dsr.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3

    sanity_row = next(r for r in result.rows if r["invoice_no"] == "KIDS26-10001")
    assert sanity_row["unit_mrp"] == Decimal("999.00")
    assert sanity_row["mrp_value"] == Decimal("999.00")
    assert sanity_row["net_value"] == Decimal("799.00")
    assert sanity_row["discount_value"] == Decimal("200.00")
    computed_discount_pct = (1 - sanity_row["net_value"] / sanity_row["mrp_value"]) * 100
    assert round(computed_discount_pct) == 20
    assert sanity_row["supplied_discount_pct"] == Decimal("20.02")  # WAD -> %

    return_row = next(r for r in result.rows if r["invoice_no"] == "0101K-019700")
    assert return_row["is_return"] is True
    assert return_row["unit_mrp"] == Decimal("899.00")  # unit price stays positive


@pytest.mark.django_db
def test_pepe_kids_financial_year_is_correctly_derived_per_row(pepe_kids_brand_and_config):
    """Same derivation as Pepe menswear (no financial_year column supplied)
    -- assumed, not yet confirmed against a real Pepe Kids file."""
    brand, config = pepe_kids_brand_and_config
    workbook = pepe_kids_workbook(PEPE_KIDS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_kids_dsr.xlsx")

    assert result.ok, result.errors
    january_row = next(r for r in result.rows if r["invoice_no"] == "KIDS26-10001")
    april_row = next(r for r in result.rows if r["invoice_no"] == "KIDS26-10083")
    assert january_row["financial_year"] == "25-26"
    assert april_row["financial_year"] == "26-27"


@pytest.mark.django_db
def test_pepe_kids_and_pepe_menswear_store_codes_dont_collide(pepe_kids_brand_and_config):
    """The entire reason this is a separate brand rather than a second
    product_line under PEPE: client-confirmed 2026-07-18 that a store
    selling both Pepe menswear and Pepe Kids uses a different store code
    for the Kids side. This just confirms brand scoping actually works."""
    brand, config = pepe_kids_brand_and_config
    kids_workbook = pepe_kids_workbook(PEPE_KIDS_GOOD_ROWS)
    run_pipeline(brand, config, kids_workbook, "pepe_kids_dsr.xlsx")

    call_command("seed_brands", stdout=StringIO())
    pepe_brand = DimBrand.objects.get(brand_code="PEPE")
    pepe_config = BrandUploadConfig.objects.get(brand=pepe_brand)
    menswear_workbook = pepe_workbook(PEPE_GOOD_ROWS)
    run_pipeline(pepe_brand, pepe_config, menswear_workbook, "pepe_dsr.xlsx")

    assert not DimStore.objects.filter(brand=pepe_brand, store_code="SIK-032").exists()
    assert not DimStore.objects.filter(brand=brand, store_code="SI-032").exists()
    assert DimStore.objects.filter(brand=brand, store_code="SIK-032").exists()
    assert DimStore.objects.filter(brand=pepe_brand, store_code="SI-032").exists()


@pytest.mark.django_db
def test_pepe_kids_good_file_resolves_dimensions_with_the_2_level_category_hierarchy(
    pepe_kids_brand_and_config,
):
    brand, config = pepe_kids_brand_and_config
    workbook = pepe_kids_workbook(PEPE_KIDS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_kids_dsr.xlsx")

    assert result.ok
    assert DimStore.objects.filter(brand=brand, store_code="SIK-032").exists()
    product = DimProduct.objects.get(brand=brand, barcode="8905875293200")
    assert product.category == "TOP WEAR"  # GEN-CAT -> category
    assert product.sub_category == "T-SHIRTS"  # CATEGORY -> sub_category


@pytest.mark.django_db
def test_pepe_kids_bad_file_fails_with_precise_actionable_errors(pepe_kids_brand_and_config):
    brand, config = pepe_kids_brand_and_config
    workbook = pepe_kids_workbook(PEPE_KIDS_BAD_ROWS)

    result = run_pipeline(brand, config, workbook, "pepe_kids_bad.xlsx")

    assert not result.ok
    by_row = {}
    for error in result.errors:
        by_row.setdefault(error.row_no, []).append(error)

    assert any(e.field == "barcode" and "missing" in e.reason for e in by_row[1])
    assert any(e.field == "quantity" and "zero quantity" in e.reason for e in by_row[2])
    assert any(
        e.field == "mrp_value" and "positive value on a return row" in e.reason for e in by_row[3]
    )
    assert any(e.field == "sale_date" for e in by_row[4])
