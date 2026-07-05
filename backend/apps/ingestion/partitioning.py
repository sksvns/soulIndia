"""Manages fact_sales' PostgreSQL declarative partitioning.

fact_sales is PARTITION BY LIST(brand_id), and each brand partition is
further PARTITION BY RANGE(sale_date) into one leaf partition per financial
year (Apr-Mar). This is purely a physical storage/pruning optimization --
it has nothing to do with the "never derive season/FY/month" business rule;
the leaf partition boundaries just happen to align with the same Apr-Mar
convention.

All functions here are idempotent: safe to call whether or not the target
partition already exists.
"""

from datetime import date

from django.db import connection


def fy_start_year(sale_date: date) -> int:
    """The calendar year a financial year (Apr-Mar) starts in, for a given date."""
    return sale_date.year if sale_date.month >= 4 else sale_date.year - 1


def fy_label(start_year: int) -> str:
    """e.g. 2023 -> '23-24', matching the string format brands supply."""
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def fy_bounds(start_year: int) -> tuple[date, date]:
    """[start, end) date range for the financial year starting in `start_year`."""
    return date(start_year, 4, 1), date(start_year + 1, 4, 1)


def _brand_partition_name(brand_id: int) -> str:
    return f"fact_sales_b{int(brand_id)}"


def _fy_partition_name(brand_id: int, start_year: int) -> str:
    return f"{_brand_partition_name(brand_id)}_fy{fy_label(int(start_year)).replace('-', '')}"


def _partition_exists(name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_class WHERE relname = %s", [name])
        return cursor.fetchone() is not None


def ensure_brand_partition(brand_id: int) -> str:
    """Create the LIST partition for a brand if it doesn't already exist."""
    brand_id = int(brand_id)
    partition_name = _brand_partition_name(brand_id)
    if _partition_exists(partition_name):
        return partition_name

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {partition_name} PARTITION OF fact_sales
                FOR VALUES IN ({brand_id})
                PARTITION BY RANGE (sale_date)
            """
        )
    return partition_name


def ensure_financial_year_partition(brand_id: int, start_year: int) -> str:
    """Create the brand partition and its FY sub-partition if either is missing."""
    brand_id = int(brand_id)
    start_year = int(start_year)
    ensure_brand_partition(brand_id)

    fy_partition = _fy_partition_name(brand_id, start_year)
    if _partition_exists(fy_partition):
        return fy_partition

    brand_partition = _brand_partition_name(brand_id)
    start, end = fy_bounds(start_year)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {fy_partition} PARTITION OF {brand_partition}
                FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')
            """
        )
    return fy_partition


def ensure_partition_for_date(brand_id: int, sale_date: date) -> str:
    """Convenience: ensure the right partition exists for a given brand+date."""
    return ensure_financial_year_partition(brand_id, fy_start_year(sale_date))
