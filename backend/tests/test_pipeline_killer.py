from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimProduct, DimStore
from tests.ingestion_fixtures import KILLER_BAD_ROWS, KILLER_GOOD_ROWS, killer_workbook


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
    # Row 3: sign mismatch (positive qty, negative net_value)
    assert any(e.field == "net_value" and "sale row" in e.reason for e in by_row[3])
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
    from tests.ingestion_fixtures import KILLER_HEADERS, build_workbook

    headers_without_store_code = [h for h in KILLER_HEADERS if h != "STORE CODE"]
    workbook = build_workbook(headers_without_store_code, rows)

    result = run_pipeline(brand, config, workbook, "no_store_code.xlsx")

    assert not result.ok
    assert any(e.field == "store_code" and "not found in file" in e.reason for e in result.errors)
