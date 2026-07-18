from unittest.mock import patch

from celery.signals import task_postrun, task_prerun

import core.celery  # noqa: F401 -- import side effect connects the signal receivers


def test_close_old_connections_is_wired_to_task_prerun_and_postrun():
    """A Celery prefork worker reuses the same DB connection across every
    task it ever runs, for as long as the worker process lives -- Django's
    usual close-if-stale behavior is normally triggered by request signals
    that never fire outside a WSGI request. Without this wired up, a
    worker that's been alive since before a live config change (e.g.
    BrandUploadConfig edited directly in the DB) keeps validating uploads
    against pre-change data until restarted -- verified against a real
    Kraus mapping fix on 2026-07-18, reproduced and fixed by wiring this.
    """
    receiver_names = {r[1]().__name__ for r in task_prerun.receivers if r[1]() is not None}
    assert "_close_old_connections" in receiver_names

    receiver_names = {r[1]().__name__ for r in task_postrun.receivers if r[1]() is not None}
    assert "_close_old_connections" in receiver_names


def test_task_prerun_signal_actually_closes_old_connections():
    with patch("django.db.close_old_connections") as mock_close:
        task_prerun.send(sender=None)
    mock_close.assert_called_once()


def test_task_postrun_signal_actually_closes_old_connections():
    with patch("django.db.close_old_connections") as mock_close:
        task_postrun.send(sender=None)
    mock_close.assert_called_once()
