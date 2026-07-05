from django.utils import timezone

from core.celery import app

from .models import UploadBatch


@app.task
def process_upload_batch(batch_id: int) -> None:
    """Proves the async pipeline end-to-end (enqueue -> worker picks it up ->
    status transitions). Day 5 replaces this body with the real parse -> map
    -> validate steps; Day 6 adds staging load + store-month replace.
    """
    batch = UploadBatch.objects.get(pk=batch_id)
    batch.status = UploadBatch.Status.PARSING
    batch.started_at = timezone.now()
    batch.save(update_fields=["status", "started_at"])
