from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import KRAUS_BAD_ROWS, KRAUS_GOOD_ROWS, kraus_workbook


@pytest.fixture
def kraus_brand_and_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KRAUS")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.mark.django_db
def test_kraus_good_file_validates_100_percent_with_correct_sanity_check_math(
    kraus_brand_and_config,
):
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_ytd_june.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3

    sanity_row = next(r for r in result.rows if r["invoice_no"] == "11009")
    assert sanity_row["unit_mrp"] == Decimal("2495.00")  # qty=1: mrp_value / quantity == mrp_value
    assert sanity_row["mrp_value"] == Decimal("2495.00")
    assert sanity_row["net_value"] == Decimal("1498.00")
    assert sanity_row["discount_value"] == Decimal("997.00")
    computed_discount_pct = (1 - sanity_row["net_value"] / sanity_row["mrp_value"]) * 100
    assert round(computed_discount_pct) == 40


@pytest.mark.django_db
def test_kraus_derives_unit_mrp_by_dividing_line_total_by_quantity(kraus_brand_and_config):
    """qty=2 row: unit_mrp must be mrp_value / quantity (1799), not the
    line-total mrp_value itself (3598) -- verified against the real file,
    where this exact qty=2 line's per-unit price matches a qty=1 line for
    the same style elsewhere in the sheet."""
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_ytd_june.xlsx")

    assert result.ok, result.errors
    qty2_row = next(r for r in result.rows if r["invoice_no"] == "11270")
    assert qty2_row["quantity"] == 2
    assert qty2_row["mrp_value"] == Decimal("3598.00")
    assert qty2_row["unit_mrp"] == Decimal("1799.00")


@pytest.mark.django_db
def test_kraus_accepts_return_row_and_keeps_unit_mrp_positive(kraus_brand_and_config):
    """Real return row shape: quantity/mrp_value/net_value all negative --
    unit_mrp is still derived as a positive per-unit price (abs()), not a
    negative one."""
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_ytd_june.xlsx")

    assert result.ok, result.errors
    return_row = next(r for r in result.rows if r["invoice_no"] == "12186")
    assert return_row["is_return"] is True
    assert return_row["quantity"] == -1
    assert return_row["mrp_value"] == Decimal("-1699.00")
    assert return_row["unit_mrp"] == Decimal("1699.00")


@pytest.mark.django_db
def test_kraus_good_file_resolves_dimensions_from_the_new_column_vocabulary(
    kraus_brand_and_config,
):
    """CATEGORY/ITEM NAME/SHADE/EAN CODE map to category/article_code/
    color/barcode -- a completely different header vocabulary from the
    original one-off sample this brand was first onboarded against."""
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_ytd_june.xlsx")

    assert result.ok
    assert DimStore.objects.filter(brand=brand, store_code="KRA-1", store_name="PANKH").exists()
    product = DimProduct.objects.get(brand=brand, barcode="8905747443917")
    assert product.category == "BAGGY"
    assert product.article_code == "LFA-2106"
    assert product.color == "DARK BLUE"


@pytest.mark.django_db
def test_kraus_store_name_casing_inconsistency_still_resolves_to_one_store(
    kraus_brand_and_config,
):
    """Real file has the same STORE CODE under two different STORE NAME
    casings ("PANKH" vs "Pankh") -- store identity resolves by STORE CODE
    alone, and store_name is uppercased unconditionally for every brand,
    so this doesn't create two stores or two different display names."""
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_ytd_june.xlsx")

    assert result.ok, result.errors
    assert DimStore.objects.filter(brand=brand, store_code="KRA-1").count() == 1
    assert DimStore.objects.get(brand=brand, store_code="KRA-1").store_name == "PANKH"


@pytest.mark.django_db
def test_kraus_bad_file_fails_with_precise_actionable_errors(kraus_brand_and_config):
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_BAD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_bad.xlsx")

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


@pytest.mark.django_db
def test_kraus_config_targets_the_sale_report_sheet_not_the_pivot_summary(kraus_brand_and_config):
    """Real file has two sheets -- "REPORT" (an 8-row pivot summary) and
    "SALE REPORT" (the 718-row detail). sheet_name must be configured
    explicitly to "SALE REPORT": the sheet-fallback (index 0 if the
    configured name isn't found) would otherwise land on the summary
    sheet instead."""
    brand, config = kraus_brand_and_config

    assert config.validation_rules["sheet_name"] == "SALE REPORT"

    workbook = kraus_workbook(KRAUS_GOOD_ROWS)
    result = run_pipeline(brand, config, workbook, "kraus_ytd_june.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3
