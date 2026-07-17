"""Real-world case: Pepe's original DSR export is multi-sheet with the
data on a sheet named 'PEPE DSR- 2026', but a client sometimes sends a
different single-sheet extract named just 'Sheet1' -- the pipeline must
not hard-fail just because the file's sheet-naming convention changed."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.parsing import read_source_file
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import (
    PEPE_GOOD_ROWS,
    PEPE_HEADERS,
    PEPE_SHEET_NAME,
    build_multi_sheet_workbook,
    build_workbook,
    pepe_workbook,
)

# Non-blank placeholder values -- an all-blank row doesn't round-trip
# through openpyxl/pandas as a real row (its bounds collapse to just the
# header), which isn't what these tests are about.
_ROW = {h: "x" for h in PEPE_HEADERS}


def test_read_source_file_uses_configured_sheet_when_present():
    buffer = pepe_workbook([_ROW])

    headers, rows = read_source_file(buffer, "pepe.xlsx", sheet_name=PEPE_SHEET_NAME)

    assert headers == PEPE_HEADERS
    assert len(rows) == 1


def test_read_source_file_falls_back_to_first_sheet_when_configured_sheet_missing():
    """The exact real-world scenario: file only has 'Sheet1', config still
    says 'PEPE DSR- 2026' -- must not raise, must read 'Sheet1'."""
    buffer = build_workbook(PEPE_HEADERS, [_ROW], sheet_name="Sheet1")

    headers, rows = read_source_file(buffer, "pepe.xlsx", sheet_name=PEPE_SHEET_NAME)

    assert headers == PEPE_HEADERS
    assert len(rows) == 1


def test_read_source_file_still_prefers_configured_sheet_over_decoy_first_sheet():
    """Regression guard: when the configured sheet genuinely exists (just
    not at index 0, matching both real Killer/Pepe files' actual shape),
    it must still be read by name, not silently swapped for the decoy."""
    decoy_row = {h: "DECOY" for h in PEPE_HEADERS}
    buffer = build_multi_sheet_workbook(
        [
            ("SUMMARY", PEPE_HEADERS, [decoy_row]),
            (PEPE_SHEET_NAME, PEPE_HEADERS, [_ROW]),
        ]
    )

    headers, rows = read_source_file(buffer, "pepe.xlsx", sheet_name=PEPE_SHEET_NAME)

    assert headers == PEPE_HEADERS
    assert rows[0] != decoy_row


@pytest.mark.django_db
def test_pepe_pipeline_accepts_a_sheet1_extract_end_to_end():
    """The actual reported case: a client's file had every column Pepe's
    config expects, but the sheet was named 'Sheet1' instead of 'PEPE DSR-
    2026' -- previously a hard failure before a single row was read, now
    the pipeline runs exactly as it would against the original naming."""
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="PEPE")
    config = BrandUploadConfig.objects.get(brand=brand)
    workbook = build_workbook(PEPE_HEADERS, PEPE_GOOD_ROWS, sheet_name="Sheet1")

    result = run_pipeline(brand, config, workbook, "pepe_sheet1_extract.xlsx")

    assert result.ok, result.errors
    assert len(result.rows) == len(PEPE_GOOD_ROWS)
