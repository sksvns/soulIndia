"""Turns one raw row (dict of raw header -> raw value) into a canonical row
dict plus an `extra` dict for unmapped columns, applying each field's `cast`
from column_map. Which raw headers are *candidates* for a canonical field is
column_resolver.resolve_columns's job (computed once per file); this module
picks the first non-blank candidate *for this row* and applies its cast --
real per-row fallback, not just a file-level default (verified against the
real Killer file: NEW EAN CODE is blank on some rows where the legacy EAN
CODE column still has a value).

A field's column_map entry may also declare `default_if_blank` (e.g.
net_value/discount_value, client-confirmed: a blank cell means 0, not a
missing/invalid row) -- when every candidate header is blank for a row,
the default is cast through the same `cast` a real value would get,
rather than the field staying None and later failing a required-field
or NOT NULL check.
"""

from . import coercion

# Season/month/financial_year/quarter are supplied-as-is per the frozen
# rule -- only whitespace-trimmed, never re-cased. Every other free-text
# dimension attribute is upper-cased for consistent filtering/grouping
# (Day 8), since it feeds the filter engine directly.
TRUSTED_AS_SUPPLIED_FIELDS = {"month", "season", "financial_year", "quarter"}
TEXT_DIMENSION_FIELDS = {
    "category",
    "sub_category",
    "color",
    "fit",
    "size",
    "gender",
    "print_type",
    "store_type",
    "zone",
    "city",
    "state",
    "distributor_name",
    "article_code",
    "store_code",
    "store_name",
}


def _json_safe(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_canonical_row(raw_row: dict, mapped: dict, unmapped: list, column_map: dict):
    """Returns (canonical: dict, extra: dict, coercion_errors: dict[field, str])."""
    canonical = {}
    coercion_errors = {}

    for canonical_field, raw_headers in mapped.items():
        raw_value = None
        for raw_header in raw_headers:
            candidate_value = raw_row.get(raw_header)
            if not coercion.is_blank(candidate_value):
                raw_value = candidate_value
                break

        spec = column_map[canonical_field]
        if raw_value is None:
            # Client-confirmed: a blank discount_value/net_value cell means
            # 0, not a missing/invalid row -- default_if_blank carries the
            # raw default through the *same* cast as a real value would
            # get, rather than a separately hardcoded typed literal here.
            default = spec.get("default_if_blank")
            if default is None:
                canonical[canonical_field] = None
                continue
            raw_value = default

        caster = coercion.CASTERS.get(spec.get("cast", "str"), coercion.to_str)
        try:
            value = caster(raw_value)
        except coercion.CoercionError as exc:
            coercion_errors[canonical_field] = str(exc)
            continue

        if isinstance(value, str):
            if canonical_field in TRUSTED_AS_SUPPLIED_FIELDS:
                value = value.strip()
            elif canonical_field in TEXT_DIMENSION_FIELDS:
                value = coercion.normalize_dimension_text(value)
        canonical[canonical_field] = value

    extra = {}
    for raw_header in unmapped:
        value = raw_row.get(raw_header)
        if not coercion.is_blank(value):
            extra[raw_header] = _json_safe(value)

    return canonical, extra, coercion_errors
