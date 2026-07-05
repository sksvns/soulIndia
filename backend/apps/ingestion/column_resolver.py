"""First slice of the mapping engine: given a brand's real file headers and
its `column_map` (docs: docs/schema.md, seed data:
apps/masterdata/seed_data/*.json), decides which headers map to which
canonical field and which are unmapped -- destined for `extra` JSONB per the
frozen "never drop a column" rule.

Day 5 builds the rest of the pipeline (pandas-based parsing, type coercion,
computed fields, dimension resolution) on top of this.
"""

import re


def normalize_header(raw: str) -> str:
    """Collapse embedded newlines/whitespace and uppercase.

    Matches the `header_normalization` convention documented in the Day 0
    mapping configs -- real source files wrap header text across lines
    (e.g. "BILL NO \\nINVOICE NO"), so headers must be compared this way,
    not by literal string equality.
    """
    return re.sub(r"\s+", " ", raw.replace("\n", " ")).strip().upper()


def resolve_columns(headers: list[str], column_map: dict) -> tuple[dict[str, str], list[str]]:
    """Returns (canonical_field -> matched raw header, unmapped raw headers).

    For canonical fields with multiple candidate sources (e.g. barcode:
    ["NEW EAN CODE", "EAN CODE"]), the first candidate present in the file
    wins.
    """
    normalized_to_raw = {normalize_header(h): h for h in headers}
    mapped: dict[str, str] = {}
    consumed = set()

    for canonical_field, spec in column_map.items():
        for candidate in spec.get("source", []):
            normalized_candidate = normalize_header(candidate)
            if normalized_candidate in normalized_to_raw and normalized_candidate not in consumed:
                mapped[canonical_field] = normalized_to_raw[normalized_candidate]
                consumed.add(normalized_candidate)
                break

    unmapped = [raw for normalized, raw in normalized_to_raw.items() if normalized not in consumed]
    return mapped, unmapped
