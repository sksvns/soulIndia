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

from calendar import monthrange
from datetime import date, timedelta

from django.db import connection, transaction
from psycopg.types.json import Jsonb

from . import dimension_resolver
from .models import UploadBatch
from .partitioning import ensure_partition_for_date

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
    """Loads validated+resolved rows (apps.ingestion.pipeline.run_pipeline's
    output) into fact_sales. Returns the slice summaries later stored on
    upload_batch.slices.

    Everything -- partition creation, staging, delete+insert per slice -- is
    one transaction: a failure at any point leaves fact_sales completely
    untouched, matching Day 5's "nothing loaded on error" guarantee extended
    to the load step itself.
    """
    if not rows:
        return []

    brand_id = batch.brand_id
    date_ids = dimension_resolver.resolve_calendar_dates(rows)
    season_ids = dimension_resolver.resolve_seasons(rows)
    slices = determine_slices(rows)

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


def rollback_batch(batch) -> int:
    """Deletes every fact_sales row tagged with this batch and marks it
    rolled_back. Returns the number of rows deleted."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM fact_sales WHERE upload_batch_id = %s", [batch.batch_id])
            deleted = cursor.rowcount
        UploadBatch.objects.filter(pk=batch.batch_id).update(status=UploadBatch.Status.ROLLED_BACK)
    return deleted
