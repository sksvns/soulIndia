"""Idempotent load into the partitioned fact_sales, per ADR-0002: for every
(store, month) slice present in a batch, DELETE existing fact rows for that
exact slice, then INSERT the new ones -- all in one transaction. Slices not
present in the upload are never touched (a correction for one store's month
can't affect any other store or month).

"Month" here means the calendar month of sale_date, not the brand's
supplied `month` text -- verified necessary against the real Killer file,
whose supplied MONTH is bare text like "APRIL" with no year, and whose
historical export spans three financial years. Grouping by that text alone
would silently merge April 2023, April 2024, and April 2025 into one slice.
"""

import logging
from calendar import monthrange
from datetime import date, timedelta

from django.db import connection, transaction
from django.db.models import Count, Max, Min, Sum
from django.db.models.functions import TruncMonth
from psycopg.types.json import Jsonb

from apps.analytics import cache as analytics_cache
from apps.analytics.materialized_views import refresh_all

from . import dimension_resolver
from .models import DataAlterationAudit, FactSales, UploadBatch
from .partitioning import ensure_partition_for_date

logger = logging.getLogger(__name__)


class DataAlterationNotPermitted(Exception):
    """Raised when a user without ingestion.alter_existing_data tries to
    replace or roll back sales data that's already loaded."""


STAGING_COLUMNS = [
    "brand_id",
    "store_id",
    "product_id",
    "date_id",
    "sale_date",
    "season_id",
    "invoice_no",
    "quantity",
    "unit_mrp",
    "mrp_value",
    "net_value",
    "discount_value",
    "is_return",
    "extra",
    "upload_batch_id",
    "source_row_no",
]

# Raw-supplied text with no first-class column/FK of its own on fact_sales
# (unlike season, which has dim_season) -- kept in `extra` per the frozen
# "trusted as-is, keep raw for audit" rule, distinct from dim_calendar's own
# *computed* financial_year/quarter for the same date.
AUDIT_TEXT_FIELDS = {
    "month": "supplied_month",
    "financial_year": "supplied_financial_year",
    "quarter": "supplied_quarter",
}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """[start, end) for one calendar month."""
    start = date(year, month, 1)
    days_in_month = monthrange(year, month)[1]
    end = date(year, month, days_in_month) + timedelta(days=1)
    return start, end


def determine_slices(rows: list[dict]) -> dict[tuple, list[dict]]:
    """Groups rows by (store_id, year, month). Returns {slice_key: [rows]}."""
    slices: dict[tuple, list[dict]] = {}
    for row in rows:
        sale_date = row["sale_date"]
        key = (row["store_id"], sale_date.year, sale_date.month)
        slices.setdefault(key, []).append(row)
    return slices


def find_conflicting_slices(brand_id: int, slices: dict) -> list[dict]:
    """Slices that already have fact_sales rows -- loading over them is an
    alteration of existing data (ADR-0003), not a fresh load. One grouped
    query covering every slice in the batch, not one query per slice -- a
    historical re-upload of a file that already has months of data loaded
    can touch hundreds of (store, month) slices at once."""
    if not slices:
        return []

    store_ids = {key[0] for key in slices}
    bounds = [month_bounds(year, month) for _, year, month in slices]
    overall_start = min(start for start, _ in bounds)
    overall_end = max(end for _, end in bounds)

    existing_counts = (
        FactSales.objects.filter(
            brand_id=brand_id,
            store_id__in=store_ids,
            sale_date__gte=overall_start,
            sale_date__lt=overall_end,
        )
        .annotate(month=TruncMonth("sale_date"))
        .values("store_id", "month")
        .annotate(existing_row_count=Count("sale_id"))
    )
    existing_by_slice = {
        (row["store_id"], row["month"].year, row["month"].month): row["existing_row_count"]
        for row in existing_counts
    }

    conflicts = []
    for store_id, year, month in slices:
        existing_count = existing_by_slice.get((store_id, year, month), 0)
        if existing_count > 0:
            conflicts.append(
                {
                    "store_id": store_id,
                    "year": year,
                    "month": month,
                    "existing_row_count": existing_count,
                }
            )
    return conflicts


def _audit_and_require_permission(
    user, brand, batch, action: str, details: dict, item_count: int
) -> None:
    """Every alteration attempt is recorded, allowed or not (ADR-0003).

    `batch` is None for a filter-based delete (brand + product_line +
    financial_year + month), which can span more than one batch -- there's
    no single batch to attribute it to, so the filter criteria live in
    `details` instead.
    """
    allowed = user.has_perm("ingestion.alter_existing_data")
    DataAlterationAudit.objects.create(
        batch=batch, user=user, brand=brand, action=action, details=details, allowed=allowed
    )
    batch_label = f"batch #{batch.batch_id}" if batch else "no single batch (filter-based)"
    if allowed:
        logger.info(
            "user %s %s existing data for brand %s (%s): %s",
            user.email,
            action,
            brand.brand_code,
            batch_label,
            details,
        )
        return

    logger.warning(
        "BLOCKED: user %s attempted to %s existing data for brand %s (%s) "
        "without Super Admin capability: %s",
        user.email,
        action,
        brand.brand_code,
        batch_label,
        details,
    )
    raise DataAlterationNotPermitted(
        f"You are altering data that requires Super Admin access ({item_count} affected item(s))."
    )


def _staging_table_name(batch_id: int) -> str:
    return f"staging_fact_sales_batch_{batch_id}"


def _build_extra(row: dict) -> dict:
    extra = dict(row.get("extra") or {})
    for field, audit_key in AUDIT_TEXT_FIELDS.items():
        value = row.get(field)
        if value:
            extra[audit_key] = value
    return extra


def _staging_row(row: dict, brand_id: int, batch_id: int, date_ids: dict, season_ids: dict) -> list:
    return [
        brand_id,
        row["store_id"],
        row["product_id"],
        date_ids[row["sale_date"]],
        row["sale_date"],
        season_ids.get(row.get("season")),
        row["invoice_no"],
        row["quantity"],
        row["unit_mrp"],
        row["mrp_value"],
        row["net_value"],
        row["discount_value"],
        row["is_return"],
        Jsonb(_build_extra(row)),
        batch_id,
        row.get("_row_no"),
    ]


def load_batch(batch, rows: list[dict]) -> list[dict]:
    """Loads validated+resolved rows (the same shape produced by
    apps.ingestion.pipeline.run_pipeline and apps.ingestion.backfill.
    run_backfill_pipeline's valid_rows) into fact_sales. Returns the slice
    summaries later stored on upload_batch.slices.

    If any target slice already has fact_sales rows, this is an alteration
    of existing data (ADR-0003) and requires the uploader to hold
    ingestion.alter_existing_data -- raises DataAlterationNotPermitted
    otherwise, before anything is touched. A fresh load into empty slices
    is never gated or audited.

    Everything -- partition creation, staging, delete+insert per slice -- is
    one transaction: a failure at any point leaves fact_sales completely
    untouched, matching Day 5's "nothing loaded on error" guarantee extended
    to the load step itself.
    """
    if not rows:
        return []

    brand_id = batch.brand_id
    slices = determine_slices(rows)

    conflicts = find_conflicting_slices(brand_id, slices)
    if conflicts:
        _audit_and_require_permission(
            batch.uploaded_by,
            batch.brand,
            batch,
            DataAlterationAudit.Action.REPLACE,
            {"slices": conflicts},
            len(conflicts),
        )

    date_ids = dimension_resolver.resolve_calendar_dates(rows)
    season_ids = dimension_resolver.resolve_seasons(rows)

    for fy_start_year in {_fy_start_year(key[1], key[2]) for key in slices}:
        ensure_partition_for_date(brand_id, date(fy_start_year, 4, 1))

    staging_table = _staging_table_name(batch.batch_id)
    slice_summaries = []

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(_create_staging_sql(staging_table))

            copy_sql = f"COPY {staging_table} ({', '.join(STAGING_COLUMNS)}) FROM STDIN"
            with cursor.copy(copy_sql) as copy:
                for row in rows:
                    copy.write_row(
                        _staging_row(row, brand_id, batch.batch_id, date_ids, season_ids)
                    )

            for (store_id, year, month), slice_rows in slices.items():
                start, end = month_bounds(year, month)
                cursor.execute(
                    "DELETE FROM fact_sales WHERE brand_id = %s AND store_id = %s "
                    "AND sale_date >= %s AND sale_date < %s",
                    [brand_id, store_id, start, end],
                )
                slice_summaries.append(
                    {
                        "store_id": store_id,
                        "year": year,
                        "month": month,
                        "row_count": len(slice_rows),
                    }
                )

            insert_columns = [c for c in STAGING_COLUMNS if c != "extra"] + ["extra"]
            cursor.execute(
                f"INSERT INTO fact_sales ({', '.join(insert_columns)}) "
                f"SELECT {', '.join(insert_columns)} FROM {staging_table}"
            )

            cursor.execute(f"DROP TABLE {staging_table}")

    return slice_summaries


def _fy_start_year(year: int, month: int) -> int:
    return year if month >= 4 else year - 1


def _create_staging_sql(table_name: str) -> str:
    return f"""
        CREATE UNLOGGED TABLE {table_name} (
            brand_id BIGINT NOT NULL,
            store_id BIGINT NOT NULL,
            product_id BIGINT NOT NULL,
            date_id BIGINT NOT NULL,
            sale_date DATE NOT NULL,
            season_id BIGINT NULL,
            invoice_no VARCHAR(64) NOT NULL,
            quantity INTEGER NOT NULL,
            unit_mrp NUMERIC(12, 2) NOT NULL,
            mrp_value NUMERIC(14, 2) NOT NULL,
            net_value NUMERIC(14, 2) NOT NULL,
            discount_value NUMERIC(14, 2) NOT NULL,
            is_return BOOLEAN NOT NULL,
            extra JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            upload_batch_id BIGINT NOT NULL,
            source_row_no INTEGER NULL
        )
    """


def rollback_batch(batch, user) -> int:
    """Deletes every fact_sales row tagged with this batch and marks it
    rolled_back. Returns the number of rows deleted.

    Removing already-loaded data is at least as sensitive as replacing it
    (ADR-0003) -- gated by the same ingestion.alter_existing_data capability
    and audited the same way, regardless of which caller invokes it (the
    Django admin action or otherwise).
    """
    existing_count = FactSales.objects.filter(batch=batch).count()
    if existing_count > 0:
        _audit_and_require_permission(
            user,
            batch.brand,
            batch,
            DataAlterationAudit.Action.ROLLBACK,
            {"row_count": existing_count},
            existing_count,
        )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM fact_sales WHERE upload_batch_id = %s", [batch.batch_id])
            deleted = cursor.rowcount
        UploadBatch.objects.filter(pk=batch.batch_id).update(status=UploadBatch.Status.ROLLED_BACK)

    if deleted:
        refresh_all()
        analytics_cache.bust(batch.brand_id)
    return deleted


def _deletable_queryset(brand, product_line: str, financial_year: str, month_no: int):
    """The exact rows a Delete Data request (brand + product_line +
    financial_year + month) would remove. Shared by preview_delete and
    delete_by_filter so the two can never drift apart -- the count/preview
    the admin confirms against is guaranteed to be the same set actually
    deleted.

    Scoped by product_line via batch -> config, not a direct fact_sales
    column (product_line only exists on BrandUploadConfig). Rows with no
    batch (upload_batch_id IS NULL) can't be resolved to a product_line and
    are excluded -- in practice this only affects synthetic load-test data,
    never real brand uploads, which always go through load_batch and always
    set a batch.
    """
    return FactSales.objects.filter(
        brand=brand,
        date__financial_year=financial_year,
        date__month_no=month_no,
        batch__config__product_line=product_line,
    )


def preview_delete(brand, product_line: str, financial_year: str, month_no: int) -> dict:
    """Read-only summary of what a Delete Data request would remove --
    never audited (nothing is altered by looking), just authorization-gated
    at the view layer."""
    return _deletable_queryset(brand, product_line, financial_year, month_no).aggregate(
        row_count=Count("sale_id"),
        store_count=Count("store_id", distinct=True),
        total_net_value=Sum("net_value"),
        min_date=Min("sale_date"),
        max_date=Max("sale_date"),
    )


def delete_by_filter(brand, product_line: str, financial_year: str, month_no: int, user) -> int:
    """Deletes every fact_sales row for one brand + product_line +
    financial_year + month, across however many upload batches loaded into
    that slice. Gated and audited exactly like rollback_batch (ADR-0003) --
    the only difference is the selection criteria (a filter, not a single
    batch), so it reuses the same permission, audit action family, and
    post-delete refresh/cache-bust steps.
    """
    existing_count = _deletable_queryset(brand, product_line, financial_year, month_no).count()
    details = {
        "product_line": product_line,
        "financial_year": financial_year,
        "month_no": month_no,
        "row_count": existing_count,
    }
    if existing_count > 0:
        _audit_and_require_permission(
            user,
            brand,
            None,
            DataAlterationAudit.Action.DELETE_FILTERED,
            details,
            existing_count,
        )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM fact_sales fs
                USING dim_calendar dc, upload_batch ub, brand_upload_config buc
                WHERE fs.date_id = dc.date_id
                  AND fs.upload_batch_id = ub.batch_id
                  AND ub.config_id = buc.config_id
                  AND fs.brand_id = %s
                  AND dc.financial_year = %s
                  AND dc.month_no = %s
                  AND buc.product_line = %s
                """,
                [brand.brand_id, financial_year, month_no, product_line],
            )
            deleted = cursor.rowcount

    if deleted:
        refresh_all()
        analytics_cache.bust(brand.brand_id)
    return deleted
