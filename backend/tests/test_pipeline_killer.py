from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import (
    KILLER_ALT_SIGN_ROWS,
    KILLER_BAD_ROWS,
    KILLER_GOOD_ROWS,
    KILLER_HEADERS,
    KILLER_SHEET_NAME,
    build_multi_sheet_workbook,
    killer_workbook,
)


@pytest.fixture
def killer_brand_and_config(db):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.mark.django_db
def test_killer_good_file_validates_100_percent_with_correct_sanity_check_math(
    killer_brand_and_config,
):
    brand, config = killer_brand_and_config
    workbook = killer_workbook(KILLER_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "killer_april.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3

    sanity_row = next(r for r in result.rows if r["invoice_no"] == "81")
    assert sanity_row["unit_mrp"] == Decimal("2499.00")
    assert sanity_row["mrp_value"] == Decimal("2499.00")
    assert sanity_row["net_value"] == Decimal("2124.00")
    assert sanity_row["discount_value"] == Decimal("375.00")
    computed_discount_pct = (1 - sanity_row["net_value"] / sanity_row["mrp_value"]) * 100
    assert round(computed_discount_pct) == 15
    assert sanity_row["is_return"] is False

    return_row = next(r for r in result.rows if r["invoice_no"] == "417")
    assert return_row["is_return"] is True
    assert return_row["quantity"] == -1
    assert return_row["unit_mrp"] == Decimal("1899.00")  # unit price stays positive
    assert return_row["mrp_value"] == Decimal("-1899.00")

    # Always-unmapped-in-practice column preserved verbatim, never dropped.
    assert sanity_row["extra"]["REPORT STATUS"] == "RECEIVED"


@pytest.mark.django_db
def test_killer_accepts_return_recorded_with_positive_quantity(killer_brand_and_config):
    """Pattern A, found loading the complete real Killer file: some returns
    are recorded with quantity left positive -- mrp_value/net_value going
    negative is what actually signals the return. Explicit product
    decision: accept and classify as is_return, not reject."""
    brand, config = killer_brand_and_config
    workbook = killer_workbook([KILLER_ALT_SIGN_ROWS[0]])

    result = run_pipeline(brand, config, workbook, "killer_pattern_a.xlsx")

    assert result.ok, result.errors
    row = result.rows[0]
    assert row["quantity"] == 1
    assert row["mrp_value"] == Decimal("-2999.00")
    assert row["is_return"] is True


@pytest.mark.django_db
def test_killer_accepts_scheme_discount_exceeding_mrp_value(killer_brand_and_config):
    """Pattern B, found loading the complete real Killer file: a flat
    scheme/coupon discount can legitimately exceed a cheap item's
    mrp_value, pushing net_value negative on an otherwise normal sale.
    Explicit product decision: accept, not a return."""
    brand, config = killer_brand_and_config
    workbook = killer_workbook([KILLER_ALT_SIGN_ROWS[1]])

    result = run_pipeline(brand, config, workbook, "killer_pattern_b.xlsx")

    assert result.ok, result.errors
    row = result.rows[0]
    assert row["quantity"] == 1
    assert row["mrp_value"] == Decimal("1899.00")
    assert row["net_value"] == Decimal("-101.00")
    assert row["is_return"] is False


@pytest.mark.django_db
def test_killer_accepts_blank_net_and_discount_value_as_zero(killer_brand_and_config):
    """Client-confirmed: a blank NET SALE VALUE or DISCOUNT VALUE cell means
    0, not a missing/invalid row that should be rejected."""
    brand, config = killer_brand_and_config
    blank_discount_row = {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 900,
        "NET \nSALE \nVALUE": None,
        "DISCOUNT \nVALUE": None,
    }
    workbook = killer_workbook([blank_discount_row])

    result = run_pipeline(brand, config, workbook, "killer_blank_discount.xlsx")

    assert result.ok, result.errors
    row = result.rows[0]
    assert row["net_value"] == Decimal("0.00")
    assert row["discount_value"] == Decimal("0.00")


@pytest.mark.django_db
def test_killer_good_file_resolves_and_creates_dimensions(killer_brand_and_config):
    brand, config = killer_brand_and_config
    workbook = killer_workbook(KILLER_GOOD_ROWS)

    result = run_pipeline(brand, config, workbook, "killer_april.xlsx")

    assert result.ok
    assert DimStore.objects.filter(brand=brand, store_code="ESIS170").exists()
    assert DimProduct.objects.filter(brand=brand, barcode="8905646454137").exists()
    for row in result.rows:
        assert row["store_id"] is not None
        assert row["product_id"] is not None


@pytest.mark.django_db
def test_killer_good_file_reuses_existing_dimensions_instead_of_duplicating(
    killer_brand_and_config,
):
    brand, config = killer_brand_and_config
    run_pipeline(brand, config, killer_workbook(KILLER_GOOD_ROWS), "batch1.xlsx")
    store_count_after_first = DimStore.objects.filter(brand=brand).count()

    run_pipeline(brand, config, killer_workbook(KILLER_GOOD_ROWS), "batch2.xlsx")

    assert DimStore.objects.filter(brand=brand).count() == store_count_after_first


@pytest.mark.django_db
def test_killer_bad_file_fails_with_precise_actionable_errors(killer_brand_and_config):
    brand, config = killer_brand_and_config
    workbook = killer_workbook(KILLER_BAD_ROWS)

    result = run_pipeline(brand, config, workbook, "killer_bad.xlsx")

    assert not result.ok
    by_row = {}
    for error in result.errors:
        by_row.setdefault(error.row_no, []).append(error)

    # Row 1: missing barcode
    assert any(e.field == "barcode" and "missing" in e.reason for e in by_row[1])
    # Row 2: zero quantity
    assert any(e.field == "quantity" and "zero quantity" in e.reason for e in by_row[2])
    # Row 3: sign mismatch (negative qty, positive mrp_value)
    assert any(e.field == "mrp_value" and "return row" in e.reason for e in by_row[3])
    # Row 4: unparseable date
    assert any(e.field == "sale_date" for e in by_row[4])


@pytest.mark.django_db
def test_killer_bad_file_creates_no_dimension_rows_at_all(killer_brand_and_config):
    brand, config = killer_brand_and_config
    workbook = killer_workbook(KILLER_BAD_ROWS)

    result = run_pipeline(brand, config, workbook, "killer_bad.xlsx")

    assert not result.ok
    assert not DimStore.objects.filter(brand=brand).exists()
    assert not DimProduct.objects.filter(brand=brand).exists()


@pytest.mark.django_db
def test_killer_file_missing_a_required_column_entirely_fails_fast(killer_brand_and_config):
    brand, config = killer_brand_and_config
    # Drop STORE CODE from the header row entirely -- a structural error,
    # not a per-row one.
    rows = [{k: v for k, v in row.items() if k != "STORE CODE"} for row in KILLER_GOOD_ROWS]
    from tests.ingestion_fixtures import build_workbook

    headers_without_store_code = [h for h in KILLER_HEADERS if h != "STORE CODE"]
    workbook = build_workbook(headers_without_store_code, rows, sheet_name=KILLER_SHEET_NAME)

    result = run_pipeline(brand, config, workbook, "no_store_code.xlsx")

    assert not result.ok
    assert any(e.field == "store_code" and "not found in file" in e.reason for e in result.errors)


@pytest.mark.django_db
def test_killer_reads_the_configured_sheet_not_sheet_index_zero(killer_brand_and_config):
    """Real Killer files are multi-sheet ('SUMMARY' then '23-24 TO 25-26
    SALE REPORT') with the transactional data on the *second* sheet --
    proves the pipeline honors validation_rules['sheet_name'] instead of
    pandas' default of reading whatever sheet is first."""
    brand, config = killer_brand_and_config
    assert config.validation_rules["sheet_name"] == KILLER_SHEET_NAME

    decoy_headers = ["SOME", "UNRELATED", "SUMMARY", "COLUMNS"]
    decoy_rows = [{"SOME": "x", "UNRELATED": "y", "SUMMARY": "z", "COLUMNS": "w"}]
    workbook = build_multi_sheet_workbook(
        [
            ("SUMMARY", decoy_headers, decoy_rows),
            (KILLER_SHEET_NAME, KILLER_HEADERS, KILLER_GOOD_ROWS),
        ]
    )

    result = run_pipeline(brand, config, workbook, "killer_multi_sheet.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == 3
