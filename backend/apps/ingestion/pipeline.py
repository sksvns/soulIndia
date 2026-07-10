"""Orchestrates parse -> map -> validate -> (Day 6: load) for one upload
batch. run_pipeline's all-or-nothing gate (Phase A must fully pass for the
*entire* file before Phase B runs at all, per plan.md Day 5) is no longer
what the upload API actually uses in production -- see
apps.ingestion.tasks.process_upload_batch and apps.ingestion.backfill for
the load-good-report-bad behavior every upload gets today. run_pipeline
itself stays here, correct and tested, since it's still a reasonable
building block (e.g. the pipeline-level test suite exercises Phase A/B
mechanics through it directly) -- it just isn't wired to an HTTP endpoint
by itself anymore.

Row-level work is chunked at 100k rows per plan.md Day 5, even though the
whole file is necessarily read into memory in one shot first -- pandas has
no true streaming reader for Excel formats (only CSV supports chunksize).
"""

from dataclasses import dataclass, field

from . import dimension_resolver, parsing, row_mapper
from .column_resolver import resolve_columns
from .derivations import apply_derived_fields
from .validation import IngestionError, validate_rows

CHUNK_SIZE = 100_000


@dataclass
class PipelineResult:
    ok: bool
    errors: list[IngestionError] = field(default_factory=list)
    rows: list[dict] | None = None  # only set when ok


@dataclass
class ParsedRows:
    canonical_rows: list[dict]
    errors: list[IngestionError]


def parse_map_validate(brand, config, fileobj, filename: str) -> ParsedRows:
    """Phase A only: parse -> map -> coerce -> validate, with no DB writes
    and no all-or-nothing gate. Shared by run_pipeline (which gates Phase B
    on zero errors) and apps.ingestion.backfill (which instead loads
    whatever subset of rows has zero errors -- the latter is what every
    upload actually uses today, see this module's docstring).
    """
    sheet_name = config.validation_rules.get("sheet_name")
    headers, raw_rows = parsing.read_source_file(fileobj, filename, sheet_name=sheet_name)
    mapped, unmapped = resolve_columns(headers, config.column_map)

    derived_fields = config.validation_rules.get("derived_fields", {})
    required_fields = config.validation_rules.get("required_canonical_fields", [])
    missing_required = [f for f in required_fields if f not in mapped and f not in derived_fields]
    if missing_required:
        return ParsedRows(
            canonical_rows=[],
            errors=[
                IngestionError(0, field_name, None, "required column not found in file")
                for field_name in missing_required
            ],
        )

    canonical_rows: list[dict] = []
    all_errors: list[IngestionError] = []

    for chunk_start in range(0, len(raw_rows), CHUNK_SIZE):
        chunk_canonical = []
        for offset, raw_row in enumerate(raw_rows[chunk_start : chunk_start + CHUNK_SIZE]):
            canonical, extra, coercion_errors = row_mapper.build_canonical_row(
                raw_row, mapped, unmapped, config.column_map
            )
            canonical["_row_no"] = chunk_start + offset + 1  # 1-indexed data row, excl. header
            canonical["_coercion_errors"] = coercion_errors
            canonical["extra"] = extra
            canonical = apply_derived_fields(canonical, config.validation_rules)
            if canonical.get("quantity") is not None:
                mrp_value = canonical.get("mrp_value")
                # A return can also show up as a positive quantity with a
                # negative mrp_value (see validation.py) -- money sign is
                # what actually signals a return in that convention.
                canonical["is_return"] = canonical["quantity"] < 0 or (
                    mrp_value is not None and mrp_value < 0
                )
            chunk_canonical.append(canonical)

        all_errors.extend(
            validate_rows(chunk_canonical, config.column_map, config.validation_rules)
        )
        canonical_rows.extend(chunk_canonical)

    return ParsedRows(canonical_rows=canonical_rows, errors=all_errors)


def run_pipeline(brand, config, fileobj, filename: str) -> PipelineResult:
    parsed = parse_map_validate(brand, config, fileobj, filename)
    if parsed.errors:
        return PipelineResult(ok=False, errors=parsed.errors)

    canonical_rows = parsed.canonical_rows
    store_ids = dimension_resolver.resolve_stores(brand, canonical_rows)
    product_ids = dimension_resolver.resolve_products(brand, canonical_rows)
    for row in canonical_rows:
        row["store_id"] = store_ids[row["store_code"]]
        row["product_id"] = product_ids[row["barcode"]]

    return PipelineResult(ok=True, rows=canonical_rows)
