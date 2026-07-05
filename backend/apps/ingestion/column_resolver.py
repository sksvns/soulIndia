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


def resolve_columns(headers: list[str], column_map: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Returns (canonical_field -> ordered list of raw headers present in
    this file, unmapped raw headers).

    A canonical field can map to *every* present candidate, not just the
    first -- verified against the real Killer file, where NEW EAN CODE is
    blank on some rows but the legacy EAN CODE column has a value on those
    same rows. Picking a single header per field at the file level would
    permanently discard that per-row fallback; row_mapper.build_canonical_row
    is what actually picks the first non-blank candidate for a given row.
    """
    normalized_to_raw = {normalize_header(h): h for h in headers}
    mapped: dict[str, list[str]] = {}
    consumed = set()

    for canonical_field, spec in column_map.items():
        candidates = []
        for candidate in spec.get("source", []):
            normalized_candidate = normalize_header(candidate)
            if normalized_candidate in normalized_to_raw:
                candidates.append(normalized_to_raw[normalized_candidate])
                consumed.add(normalized_candidate)
        if candidates:
            mapped[canonical_field] = candidates

    unmapped = [raw for normalized, raw in normalized_to_raw.items() if normalized not in consumed]
    return mapped, unmapped
