import logging

from django.utils import timezone

from core.celery import app

from .backfill import execute_backfill
from .models import UploadBatch

logger = logging.getLogger(__name__)


@app.task
def process_upload_batch(batch_id: int) -> None:
    """parse -> map -> validate -> load, per plan.md Days 5-6, revised to
    load-good-report-bad for every upload (not just the one-time backfill
    path -- see apps.ingestion.backfill and its module docstring for why
    this used to be all-or-nothing and no longer is). On *any* other
    failure -- storage outage, DB error, a bug -- the batch still ends up
    visibly "failed" with a reason, never silently stuck mid-pipeline; the
    exception is re-raised so Celery's own error tracking still sees it
    too. Shared by both the regular /uploads/ endpoint and the
    Super-Admin-only /backfill/ endpoint -- same task, same behavior;
    /backfill/'s permission gate is about who may touch already-loaded
    data (ADR-0003, enforced inside load_batch itself), not about this
    load-good-report-bad behavior, which every upload now gets.
    """
    batch = UploadBatch.objects.select_related("brand", "config").get(pk=batch_id)
    batch.status = UploadBatch.Status.VALIDATING
    batch.started_at = timezone.now()
    batch.save(update_fields=["status", "started_at"])
    try:
        execute_backfill(batch)
    except Exception as exc:
        logger.exception("batch #%s: failed with a system error", batch_id)
        batch.status = UploadBatch.Status.FAILED
        batch.failure_reason = str(exc)[:2000]
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "failure_reason", "finished_at"])
        raise
