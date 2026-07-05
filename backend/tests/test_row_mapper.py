from apps.ingestion.row_mapper import build_canonical_row

COLUMN_MAP = {
    "sale_date": {"source": ["NEW DATE"], "cast": "excel_serial_date"},
    "store_code": {"source": ["STORE CODE"], "cast": "str"},
    "barcode": {"source": ["NEW EAN CODE", "EAN CODE"], "cast": "barcode"},
    "category": {"source": ["MAIN CATEGORY"], "cast": "str"},
    "season": {"source": ["SEASON"], "cast": "str", "trusted_as_supplied": True},
    "unit_mrp": {"source": ["MRP"], "cast": "decimal"},
    "quantity": {"source": ["QTY SALE"], "cast": "int"},
}


def test_build_canonical_row_maps_coerces_and_normalizes():
    raw_row = {
        "NEW DATE": 45017,
        "STORE CODE": "esis170",
        "NEW EAN CODE": 8905646747185.0,
        "MAIN CATEGORY": "  shirts  ",
        "SEASON": " ss23 ",
        "MRP": 1399,
        "QTY SALE": 1,
        "SOME UNKNOWN COLUMN": "mystery",
    }
    mapped = {
        "sale_date": ["NEW DATE"],
        "store_code": ["STORE CODE"],
        "barcode": ["NEW EAN CODE", "EAN CODE"],
        "category": ["MAIN CATEGORY"],
        "season": ["SEASON"],
        "unit_mrp": ["MRP"],
        "quantity": ["QTY SALE"],
    }
    unmapped = ["SOME UNKNOWN COLUMN"]

    canonical, extra, errors = build_canonical_row(raw_row, mapped, unmapped, COLUMN_MAP)

    assert errors == {}
    assert canonical["barcode"] == "8905646747185"
    assert canonical["category"] == "SHIRTS"  # dimension text: upper-cased
    assert canonical["season"] == "ss23"  # trusted as supplied: only trimmed
    assert canonical["store_code"] == "ESIS170"
    assert extra == {"SOME UNKNOWN COLUMN": "mystery"}


def test_build_canonical_row_falls_back_to_second_candidate_when_first_is_blank_for_this_row():
    """Real Killer data: NEW EAN CODE is blank on some rows where the legacy
    EAN CODE column still has a value -- must fall back per row, not just
    when the primary header is absent from the file entirely."""
    raw_row = {"NEW EAN CODE": None, "EAN CODE": 607827, "STORE CODE": "ESIS190"}
    mapped = {"barcode": ["NEW EAN CODE", "EAN CODE"], "store_code": ["STORE CODE"]}

    canonical, extra, errors = build_canonical_row(raw_row, mapped, [], COLUMN_MAP)

    assert canonical["barcode"] == "607827"
    assert errors == {}


def test_build_canonical_row_records_coercion_errors_without_raising():
    raw_row = {"NEW DATE": "not-a-date", "STORE CODE": "ESIS170"}
    mapped = {"sale_date": ["NEW DATE"], "store_code": ["STORE CODE"]}

    canonical, extra, errors = build_canonical_row(raw_row, mapped, [], COLUMN_MAP)

    assert "sale_date" in errors
    assert "sale_date" not in canonical
    assert canonical["store_code"] == "ESIS170"


def test_build_canonical_row_blank_values_become_none_not_errors():
    raw_row = {"NEW EAN CODE": None, "STORE CODE": "ESIS170"}
    mapped = {"barcode": ["NEW EAN CODE"], "store_code": ["STORE CODE"]}

    canonical, extra, errors = build_canonical_row(raw_row, mapped, [], COLUMN_MAP)

    assert canonical["barcode"] is None
    assert errors == {}


def test_build_canonical_row_skips_blank_unmapped_values_in_extra():
    raw_row = {"STORE CODE": "ESIS170", "EMPTY COLUMN": None}
    mapped = {"store_code": ["STORE CODE"]}

    canonical, extra, errors = build_canonical_row(raw_row, mapped, ["EMPTY COLUMN"], COLUMN_MAP)

    assert extra == {}
