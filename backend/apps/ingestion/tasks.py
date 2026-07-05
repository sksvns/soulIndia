import io
import logging

from django.db import transaction
from django.utils import timezone

from core.celery import app

from . import storage
from .error_report import build_error_report_csv
from .loader import DataAlterationNotPermitted, load_batch
from .models import UploadBatch
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _run(batch: UploadBatch) -> None:
    logger.info(
        "batch #%s: parsing started (%s, %s)",
        batch.batch_id,
        batch.brand.brand_code,
        batch.file_name,
    )
    batch.status = UploadBatch.Status.PARSING
    batch.started_at = timezone.now()
    batch.save(update_fields=["status", "started_at"])

    raw_bytes = storage.get(batch.object_key).read()

    batch.status = UploadBatch.Status.VALIDATING
    batch.save(update_fields=["status"])

    # Phase B (dimension resolution) is the only DB-writing part of the
    # pipeline, and only runs once every row in the file has passed Phase A
    # validation -- but wrapping the whole call in a transaction means a
    # failure discovered *during* Phase B still leaves nothing behind.
    with transaction.atomic():
        result = run_pipeline(batch.brand, batch.config, io.BytesIO(raw_bytes), batch.file_name)
        if not result.ok:
            transaction.set_rollback(True)

    if not result.ok:
        logger.warning(
            "batch #%s: validation failed with %d error(s)", batch.batch_id, len(result.errors)
        )
        report_key = f"error-reports/{batch.batch_id}.csv"
        storage.put(
            report_key, io.BytesIO(build_error_report_csv(result.errors)), content_type="text/csv"
        )
        batch.status = UploadBatch.Status.FAILED
        batch.error_count = len(result.errors)
        batch.error_report_key = report_key
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "error_count", "error_report_key", "finished_at"])
        return

    logger.info("batch #%s: validation passed, %d row(s)", batch.batch_id, len(result.rows))

    # Load: store-month replace (ADR-0002), one transaction. TODO(Day 7):
    # refresh the affected materialized views and bust their Redis cache
    # keys here once mv_sales_summary/mv_store_perf/mv_category_perf exist.
    try:
        slices = load_batch(batch, result.rows)
    except DataAlterationNotPermitted as exc:
        # A clean, expected rejection (ADR-0003) -- not a system error, so
        # it's handled here rather than by process_upload_batch's catch-all.
        batch.status = UploadBatch.Status.FAILED
        batch.failure_reason = str(exc)
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "failure_reason", "finished_at"])
        return

    batch.status = UploadBatch.Status.LOADED
    batch.row_count = len(result.rows)
    batch.error_count = 0
    batch.slices = slices
    batch.finished_at = timezone.now()
    batch.save(update_fields=["status", "row_count", "error_count", "slices", "finished_at"])
    logger.info(
        "batch #%s: loaded %d row(s) across %d slice(s)",
        batch.batch_id,
        len(result.rows),
        len(slices),
    )


@app.task
def process_upload_batch(batch_id: int) -> None:
    """parse -> map -> validate -> load, per plan.md Days 5-6. On any row
    error the whole batch fails with a downloadable report and nothing is
    persisted. On *any* other failure -- storage outage, DB error, a bug --
    the batch still ends up visibly "failed" with a reason, never silently
    stuck mid-pipeline; the exception is re-raised so Celery's own error
    tracking still sees it too.
    """
    batch = UploadBatch.objects.select_related("brand", "config").get(pk=batch_id)
    try:
        _run(batch)
    except Exception as exc:
        logger.exception("batch #%s: failed with a system error", batch_id)
        batch.status = UploadBatch.Status.FAILED
        batch.failure_reason = str(exc)[:2000]
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "failure_reason", "finished_at"])
        raise
