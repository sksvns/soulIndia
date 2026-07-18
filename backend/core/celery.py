import os

from celery import Celery
from celery.signals import task_postrun, task_prerun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@task_prerun.connect
@task_postrun.connect
def _close_old_connections(**kwargs):
    """A prefork worker reuses the same DB connection across every task it
    ever runs, for as long as the worker process lives. Django's usual
    close-if-stale behavior (django.db.close_old_connections) is normally
    triggered by the request_started/request_finished signals in a WSGI
    context -- Celery tasks aren't requests, so those signals never fire
    here, and nothing was closing this worker's connection between tasks.

    Verified 2026-07-18: a live BrandUploadConfig fix (Kraus's column
    mapping, updated directly in the DB via seed_upload_configs, not a
    full redeploy) wasn't picked up by an already-running worker at all --
    every upload it processed kept validating against the pre-fix mapping
    until the worker was restarted, even though a fresh connection (a
    plain shell, or a different worker) saw the fix immediately. Closing
    the connection at the start and end of every task forces a fresh one
    next query, so a long-lived worker can never run stale against data
    that's changed since it started.
    """
    from django.db import close_old_connections

    close_old_connections()
