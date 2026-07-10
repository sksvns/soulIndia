"""Load-good-report-bad ingestion (originally built for one-time historical
backfill, plan.md Day 12: "load real historical files per brand" -- see
ADR-0005 for that history). Confirmed loading the actual production Killer
file: 11,760 of 748,161 rows (1.6%) had genuine data-quality issues, and
blocking the *entire* load on every row being perfect first would withhold
revenue history the client already has elsewhere for an indefinite
correction cycle. So this module parses+validates the whole file (the
same Phase A used everywhere else), loads every row that passes, and
reports every row that doesn't in one CSV -- nothing is silently dropped,
it's just reported instead of blocking the rest.

`process_upload_batch` (apps.ingestion.tasks) now uses this for every
upload, not just backfill -- ADR-0005 originally scoped this to a
Super-Admin-only /backfill/ endpoint, kept separate from the regular
/uploads/ endpoint's all-or-nothing behavior; that scoping decision was
later reversed (any bad row was rejecting entire real files with only a
handful of bad rows in them, which wasn't the intended day-to-day
experience). `run_pipeline` in pipeline.py -- the original all-or-nothing
gate -- still exists and is still tested/used directly by pipeline-level
tests, it's just no longer what the upload endpoints call.
"""

import io
import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.analytics import cache as analytics_cache
from apps.analytics.materialized_views import refresh_all

from . import dimension_resolver, storage
from .error_report import build_error_report_csv
from .loader import DataAlterationNotPermitted, load_batch
from .models import UploadBatch
from .pipeline import parse_map_validate
from .validation import IngestionError

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    valid_rows: list[dict]
    errors: list[IngestionError]
    total_rows: int


def run_backfill_pipeline(brand, config, fileobj, filename: str) -> BackfillResult:
    parsed = parse_map_validate(brand, config, fileobj, filename)
    bad_row_nos = {error.row_no for error in parsed.errors}
    valid_rows = [row for row in parsed.canonical_rows if row["_row_no"] not in bad_row_nos]

    if valid_rows:
        store_ids = dimension_resolver.resolve_stores(brand, valid_rows)
        product_ids = dimension_resolver.resolve_products(brand, valid_rows)
        for row in valid_rows:
            row["store_id"] = store_ids[row["store_code"]]
            row["product_id"] = product_ids[row["barcode"]]

    return BackfillResult(
        valid_rows=valid_rows,
        errors=parsed.errors,
        total_rows=len(parsed.canonical_rows),
    )


def execute_backfill(batch: UploadBatch) -> BackfillResult:
    """Shared orchestration for the backfill_historical management command
    and both the regular /uploads/ and Super-Admin-only /backfill/ API
    endpoints (via apps.ingestion.tasks.process_upload_batch): parse+
    validate the raw file already sitting at batch.object_key, load
    whatever rows pass, and leave the batch's status/row_count/error_count/
    error_report_key/slices fully reflecting the outcome either way.
    Callers only need to create the batch (with the raw file already
    stored) and interpret the result.

    A permission rejection (ADR-0003 -- this batch would replace/touch a
    slice that already has data, and the uploader lacks
    ingestion.alter_existing_data) is handled here, not re-raised: it's an
    expected, clean outcome, not a system error.
    """
    raw_bytes = storage.get(batch.object_key).read()

    with transaction.atomic():
        result = run_backfill_pipeline(
            batch.brand, batch.config, io.BytesIO(raw_bytes), batch.file_name
        )

    report_key = None
    if result.errors:
        report_key = f"error-reports/{batch.batch_id}.csv"
        storage.put(
            report_key,
            io.BytesIO(build_error_report_csv(result.errors)),
            content_type="text/csv",
        )

    if not result.valid_rows:
        batch.status = UploadBatch.Status.FAILED
        batch.error_count = len(result.errors)
        batch.error_report_key = report_key
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "error_count", "error_report_key", "finished_at"])
        return result

    try:
        slices = load_batch(batch, result.valid_rows)
    except DataAlterationNotPermitted as exc:
        batch.status = UploadBatch.Status.FAILED
        batch.failure_reason = str(exc)
        batch.error_count = len(result.errors)
        batch.error_report_key = report_key
        batch.finished_at = timezone.now()
        batch.save(
            update_fields=[
                "status",
                "failure_reason",
                "error_count",
                "error_report_key",
                "finished_at",
            ]
        )
        return result

    refresh_all()
    analytics_cache.bust(batch.brand_id)

    # LOADED (not a new status) -- row_count/error_count together tell the
    # whole story: this is the same "batch" the regular API's serializer
    # already exposes, just with error_count > 0 meaning "N rows skipped,
    # reported" instead of the regular path's implicit "0, because any
    # error would have failed the whole batch."
    batch.status = UploadBatch.Status.LOADED
    batch.row_count = len(result.valid_rows)
    batch.error_count = len(result.errors)
    batch.error_report_key = report_key
    batch.slices = slices
    batch.finished_at = timezone.now()
    batch.save(
        update_fields=[
            "status",
            "row_count",
            "error_count",
            "error_report_key",
            "slices",
            "finished_at",
        ]
    )
    logger.info(
        "batch #%s: backfill loaded %d/%d row(s) across %d slice(s), %d rejected",
        batch.batch_id,
        len(result.valid_rows),
        result.total_rows,
        len(slices),
        len(result.errors),
    )
    return result
