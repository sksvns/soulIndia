from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import (
    JUNIOR_KILLER_BAD_ROWS,
    JUNIOR_KILLER_GOOD_ROWS,
    JUNIOR_KILLER_HEADERS,
    JUNIOR_KILLER_SHEET_NAME,
    build_multi_sheet_workbook,
    junior_killer_workbook,
)

# Hand totals from JUNIOR_KILLER_GOOD_ROWS: row1 (SHIRTS, no discount)
# mrp=1299 net=1299 disc=0; row2 (JEANS, discounted) mrp=1599 net=1299
# disc=300; row3 (return) mrp=-1299 net=-1299 disc=0.
# total mrp=1299+1599-1299=1599, net=1299+1299-1299=1299, disc=300, qty=1.
EXPECTED_TOTAL_MRP = Decimal("1599.00")
EXPECTED_TOTAL_NET = Decimal("1299.00")
EXPECTED_TOTAL_DISCOUNT = Decimal("300.00")


@pytest.fixture
def junior_killer_brand_and_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="JUNIOR_KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.mark.django_db
def test_junior_killer_good_file_validates_with_correct_math(junior_killer_brand_and_config):
    brand, config = junior_killer_brand_and_config
    workbook = junior_killer_workbook(JUNIOR_KILLER_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "junior_killer_april.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3

    total_mrp = sum(r["mrp_value"] for r in result.rows)
    total_net = sum(r["net_value"] for r in result.rows)
    total_discount = sum(r["discount_value"] for r in result.rows)
    assert total_mrp == EXPECTED_TOTAL_MRP
    assert total_net == EXPECTED_TOTAL_NET
    assert total_discount == EXPECTED_TOTAL_DISCOUNT

    sale_row = next(r for r in result.rows if r["invoice_no"] == "0101-0022555")
    assert sale_row["unit_mrp"] == Decimal("1299.00")
    assert sale_row["is_return"] is False

    return_row = next(r for r in result.rows if r["invoice_no"] == "0101-0033012")
    assert return_row["is_return"] is True
    assert return_row["quantity"] == -1
    assert return_row["unit_mrp"] == Decimal("1299.00")  # unit price stays positive

    # BRAND is always-unmapped in practice (redundant with the upload
    # context) -> preserved in extra, never dropped.
    assert sale_row["extra"]["BRAND"] == "JR KILLER"


@pytest.mark.django_db
def test_junior_killer_good_file_resolves_and_creates_dimensions(junior_killer_brand_and_config):
    brand, config = junior_killer_brand_and_config
    workbook = junior_killer_workbook(JUNIOR_KILLER_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "junior_killer_april.xlsx")

    assert result.ok
    assert DimStore.objects.filter(brand=brand, store_code="JKESIS011").exists()
    assert DimProduct.objects.filter(brand=brand, barcode="8905935224182").exists()
    for row in result.rows:
        assert row["store_id"] is not None
        assert row["product_id"] is not None


@pytest.mark.django_db
def test_junior_killer_and_killer_store_codes_dont_collide(junior_killer_brand_and_config):
    """JK-prefixed store codes (JKESIS011) vs Killer's ESIS### are a
    different namespace, but store_code is only unique *within* a brand
    (frozen decision) -- this just confirms brand scoping actually works,
    not that the prefixes matter."""
    brand, config = junior_killer_brand_and_config
    workbook = junior_killer_workbook(JUNIOR_KILLER_GOOD_ROWS)

    run_pipeline(brand, config, workbook, "junior_killer_april.xlsx")

    assert not DimStore.objects.filter(brand__brand_code="KILLER").exists()
    assert DimStore.objects.filter(brand=brand).exists()


@pytest.mark.django_db
def test_junior_killer_bad_file_fails_with_precise_actionable_errors(
    junior_killer_brand_and_config,
):
    brand, config = junior_killer_brand_and_config
    workbook = junior_killer_workbook(JUNIOR_KILLER_BAD_ROWS)

    result = run_pipeline(brand, config, workbook, "junior_killer_bad.xlsx")

    assert not result.ok
    by_row = {}
    for error in result.errors:
        by_row.setdefault(error.row_no, []).append(error)

    assert any(e.field == "barcode" and "missing" in e.reason for e in by_row[1])
    assert any(e.field == "quantity" and "zero quantity" in e.reason for e in by_row[2])
    assert any(e.field == "mrp_value" and "return row" in e.reason for e in by_row[3])
    assert any(e.field == "sale_date" for e in by_row[4])


@pytest.mark.django_db
def test_junior_killer_reads_the_configured_sheet_not_sheet_index_zero(
    junior_killer_brand_and_config,
):
    """Real file's sheets are ['Sheet2', 'Sheet1'] -- the transactional
    data is on 'Sheet1', which is NOT index 0."""
    brand, config = junior_killer_brand_and_config
    assert config.validation_rules["sheet_name"] == JUNIOR_KILLER_SHEET_NAME

    decoy_headers = ["SOME", "UNRELATED", "PIVOT", "COLUMNS"]
    decoy_rows = [{"SOME": "x", "UNRELATED": "y", "PIVOT": "z", "COLUMNS": "w"}]
    workbook = build_multi_sheet_workbook(
        [
            ("Sheet2", decoy_headers, decoy_rows),
            (JUNIOR_KILLER_SHEET_NAME, JUNIOR_KILLER_HEADERS, JUNIOR_KILLER_GOOD_ROWS),
        ]
    )

    result = run_pipeline(brand, config, workbook, "junior_killer_multi_sheet.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3
