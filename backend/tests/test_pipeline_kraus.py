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

    result = run_pipeline(brand, config, workbook, "kraus_sales.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3

    sanity_row = next(r for r in result.rows if r["invoice_no"] == "0202-0015279")
    assert sanity_row["unit_mrp"] == Decimal("1599.00")  # derived: mrp_value / quantity
    assert sanity_row["mrp_value"] == Decimal("1599.00")
    assert sanity_row["net_value"] == Decimal("1439.09")
    assert sanity_row["discount_value"] == Decimal("159.90")
    computed_discount_pct = (1 - sanity_row["net_value"] / sanity_row["mrp_value"]) * 100
    assert round(computed_discount_pct) == 10
    assert sanity_row["supplied_discount_pct"] == Decimal(
        "10.00"
    )  # already a plain %, not a fraction


@pytest.mark.django_db
def test_kraus_accepts_return_row_and_keeps_unit_mrp_positive(kraus_brand_and_config):
    """Real return row shape: quantity/mrp_value/net_value all negative,
    invoice_no carries an 'R' infix -- unit_mrp is still derived as a
    positive per-unit price (abs()), not a negative one."""
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_sales.xlsx")

    assert result.ok, result.errors
    return_row = next(r for r in result.rows if r["invoice_no"] == "0202R-000625")
    assert return_row["is_return"] is True
    assert return_row["quantity"] == -1
    assert return_row["mrp_value"] == Decimal("-1599.00")
    assert return_row["unit_mrp"] == Decimal("1599.00")


@pytest.mark.django_db
def test_kraus_good_file_resolves_dimensions_with_article_no_as_category(
    kraus_brand_and_config,
):
    """Client-confirmed: ARTICLE NO (only 4 distinct values in the real
    file -- a garment type, not a per-SKU code) maps to category; the
    real per-SKU code is STYLE NAME, mapped to article_code."""
    brand, config = kraus_brand_and_config
    workbook = kraus_workbook(KRAUS_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "kraus_sales.xlsx")

    assert result.ok
    assert DimStore.objects.filter(
        brand=brand, store_code="02", store_name="THE BOMBAY FASHION"
    ).exists()
    product = DimProduct.objects.get(brand=brand, barcode="8905747590116")
    assert product.category == "L TOP"
    assert product.article_code == "LTA-2338"


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
def test_kraus_has_no_configured_sheet_name_defaults_to_first_sheet(kraus_brand_and_config):
    """Unlike Killer/Pepe/Junior Killer, Kraus's real sample file is a
    single unnamed sheet -- no validation_rules['sheet_name'] is
    configured at all, relying on the default (sheet index 0)."""
    brand, config = kraus_brand_and_config
    assert "sheet_name" not in config.validation_rules

    workbook = kraus_workbook(KRAUS_GOOD_ROWS)
    result = run_pipeline(brand, config, workbook, "kraus_sales.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3
