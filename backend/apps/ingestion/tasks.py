import io
import logging

from django.db import transaction
from django.utils import timezone

from core.celery import app

from . import storage
from .error_report import build_error_report_csv
from .models import UploadBatch
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _run(batch: UploadBatch) -> None:
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

    batch.row_count = len(result.rows)
    batch.error_count = 0
    batch.save(update_fields=["row_count", "error_count"])


@app.task
def process_upload_batch(batch_id: int) -> None:
    """parse -> map -> validate, per plan.md Day 5. On any row error the
    whole batch fails with a downloadable report and nothing is persisted.
    On *any* other failure -- storage outage, DB error, a bug -- the batch
    still ends up visibly "failed" with a reason, never silently stuck
    mid-pipeline; the exception is re-raised so Celery's own error tracking
    still sees it too.

    Day 6 continues from a successful "validating" state: COPY into staging,
    determine (store, month) slices, replace within one transaction, refresh
    materialized views, and finally mark the batch "loaded".
    """
    batch = UploadBatch.objects.select_related("brand", "config").get(pk=batch_id)
    try:
        _run(batch)
    except Exception as exc:
        logger.exception("upload batch %s failed with a system error", batch_id)
        batch.status = UploadBatch.Status.FAILED
        batch.failure_reason = str(exc)[:2000]
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "failure_reason", "finished_at"])
        raise
