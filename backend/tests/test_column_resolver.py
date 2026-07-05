import json
from pathlib import Path

from apps.ingestion.column_resolver import normalize_header, resolve_columns

SEED_DATA_DIR = Path(__file__).resolve().parent.parent / "apps/masterdata/seed_data"


def _load_config(filename):
    return json.loads((SEED_DATA_DIR / filename).read_text())


def test_normalize_header_collapses_newlines_and_whitespace():
    assert normalize_header("BILL NO \nINVOICE NO") == "BILL NO INVOICE NO"
    assert normalize_header("MAIN\nCATEGORY") == "MAIN CATEGORY"
    assert normalize_header("  Store Name  ") == "STORE NAME"


def test_killer_real_headers_all_resolve_with_one_unknown_column_as_extra():
    config = _load_config("killer_menswear.json")
    # A representative slice of Killer's real 34 columns, plus one column
    # that has never appeared in any brand's mapping -- proves an unknown
    # column is preserved (routed to "unmapped"/extra), never dropped.
    headers = [
        "INVOICE\nDATE",
        "NEW DATE",
        "MONTH",
        "BILL NO \nINVOICE NO",
        "STORE CODE",
        "NAME",
        "EAN CODE",
        "NEW EAN CODE",
        "MAIN\nCATEGORY",
        "ITEM NAME",
        "CATEGORY",
        "MRP",
        "QTY \nSALE",
        "MRP \nSALE \nVALUE",
        "NET \nSALE \nVALUE",
        "DISCOUNT \nVALUE",
        "F. YEAR",
        "SUPER SECRET FIELD",
    ]

    mapped, unmapped = resolve_columns(headers, config["column_map"])

    assert mapped["sale_date"] == ["NEW DATE"]
    assert mapped["invoice_no"] == ["BILL NO \nINVOICE NO"]
    assert mapped["store_code"] == ["STORE CODE"]
    # Both barcode candidates present in this file -- both kept as
    # per-row fallback candidates, in config-priority order.
    assert mapped["barcode"] == ["NEW EAN CODE", "EAN CODE"]
    assert mapped["article_code"] == ["ITEM NAME"]
    assert mapped["category"] == ["MAIN\nCATEGORY"]
    assert mapped["sub_category"] == ["CATEGORY"]
    assert mapped["financial_year"] == ["F. YEAR"]

    assert "SUPER SECRET FIELD" in unmapped
    assert "INVOICE\nDATE" in unmapped  # legacy secondary date column, not authoritative
    # EAN CODE is a real mapped candidate now (per-row fallback), not extra.
    assert "EAN CODE" not in unmapped


def test_barcode_maps_to_ean_code_alone_when_new_ean_code_column_is_absent():
    config = _load_config("killer_menswear.json")
    headers = ["EAN CODE", "STORE CODE"]

    mapped, unmapped = resolve_columns(headers, config["column_map"])

    assert mapped["barcode"] == ["EAN CODE"]
    assert "EAN CODE" not in unmapped


def test_pepe_real_headers_resolve_with_one_unknown_column_as_extra():
    config = _load_config("pepe_menswear.json")
    headers = [
        "Store Name",
        "CITY",
        "STORE CODE",
        "MONTH",
        "QUARTERS",
        "DATE",
        "BillNo",
        "STOCKNo",
        "PC9",
        "MRP",
        "Units",
        "Total MRP",
        "Net Sale Price",
        "Actual Disc",
        "WAD",
        "GENDER",
        "GEN - CAT",
        "CATEGORY",
        "SEASON",
        "A BRAND NEW COLUMN NOBODY MAPPED",
    ]

    mapped, unmapped = resolve_columns(headers, config["column_map"])

    assert mapped["sale_date"] == ["DATE"]
    assert mapped["invoice_no"] == ["BillNo"]
    assert mapped["barcode"] == ["STOCKNo"]
    assert mapped["article_code"] == ["PC9"]
    assert mapped["category"] == ["GEN - CAT"]
    assert mapped["sub_category"] == ["CATEGORY"]
    assert mapped["supplied_discount_pct"] == ["WAD"]

    assert "A BRAND NEW COLUMN NOBODY MAPPED" in unmapped
