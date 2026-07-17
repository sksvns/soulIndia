"""REFRESH MATERIALIZED VIEW CONCURRENTLY cannot run inside a transaction
block, so this must only ever be called *after* the load transaction
(apps.ingestion.loader.load_batch) has committed -- apps.ingestion.tasks
does exactly that.
"""

import logging

from django.db import connection

logger = logging.getLogger(__name__)

MATERIALIZED_VIEWS = ["mv_store_perf", "mv_category_perf", "mv_color_perf", "mv_size_perf"]


def refresh_all() -> None:
    with connection.cursor() as cursor:
        for view_name in MATERIALIZED_VIEWS:
            cursor.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}")
    logger.info("refreshed materialized views: %s", ", ".join(MATERIALIZED_VIEWS))
