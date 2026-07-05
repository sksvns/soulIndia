from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from apps.ingestion.models import FactSales
from apps.ingestion.partitioning import (
    ensure_brand_partition,
    ensure_financial_year_partition,
    ensure_partition_for_date,
    fy_bounds,
    fy_label,
    fy_start_year,
)
from apps.masterdata.models import DimBrand, DimCalendar, DimProduct, DimStore


def _partition_table_exists(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_class WHERE relname = %s", [name])
        return cursor.fetchone() is not None


def _row_count_in_table(name):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM {name}"
        )  # test-only: name is our own generated format
        return cursor.fetchone()[0]


def test_fy_helpers():
    assert fy_start_year(date(2023, 4, 1)) == 2023
    assert fy_start_year(date(2024, 3, 31)) == 2023
    assert fy_start_year(date(2026, 1, 15)) == 2025
    assert fy_label(2023) == "23-24"
    assert fy_bounds(2023) == (date(2023, 4, 1), date(2024, 4, 1))


@pytest.mark.django_db
def test_creating_a_brand_auto_creates_its_partition():
    brand = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")

    assert _partition_table_exists(f"fact_sales_b{brand.brand_id}")


@pytest.mark.django_db
def test_new_brand_row_routes_into_its_own_financial_year_partition():
    killer = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")
    pepe = DimBrand.objects.create(brand_code="PEPE", brand_name="Pepe")

    ensure_financial_year_partition(killer.brand_id, 2023)
    ensure_financial_year_partition(pepe.brand_id, 2023)

    store = DimStore.objects.create(brand=killer, store_code="ESIS170", store_name="Aadarsh")
    product = DimProduct.objects.create(brand=killer, barcode="8905646747185")
    sale_date = date(2023, 4, 5)
    cal = DimCalendar.objects.create(
        date=sale_date, day=5, month_no=4, month_name="April", quarter=1, financial_year="23-24"
    )

    FactSales.objects.create(
        brand=killer,
        store=store,
        product=product,
        date=cal,
        sale_date=sale_date,
        invoice_no="21",
        quantity=1,
        unit_mrp=Decimal("1399.00"),
        mrp_value=Decimal("1399.00"),
        net_value=Decimal("1190.00"),
        discount_value=Decimal("209.00"),
    )

    killer_partition = f"fact_sales_b{killer.brand_id}_fy2324"
    pepe_partition = f"fact_sales_b{pepe.brand_id}_fy2324"
    assert _row_count_in_table(killer_partition) == 1
    assert _row_count_in_table(pepe_partition) == 0


@pytest.mark.django_db
def test_ensure_partition_for_date_matches_manual_fy_partition():
    brand = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")

    partition_name = ensure_partition_for_date(brand.brand_id, date(2025, 6, 10))

    assert partition_name == f"fact_sales_b{brand.brand_id}_fy2526"
    assert _partition_table_exists(partition_name)


@pytest.mark.django_db
def test_insert_outside_any_partition_range_is_rejected():
    killer = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")
    ensure_financial_year_partition(killer.brand_id, 2023)  # covers Apr 2023 - Mar 2024 only

    store = DimStore.objects.create(brand=killer, store_code="ESIS170", store_name="Aadarsh")
    product = DimProduct.objects.create(brand=killer, barcode="8905646747185")
    uncovered_date = date(2025, 1, 1)
    cal = DimCalendar.objects.create(
        date=uncovered_date,
        day=1,
        month_no=1,
        month_name="January",
        quarter=4,
        financial_year="24-25",
    )

    # Postgres raises a check_violation ("no partition of relation found for
    # row") when no leaf partition covers the row's sale_date; Django's
    # backend maps that SQLSTATE class to IntegrityError.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            FactSales.objects.create(
                brand=killer,
                store=store,
                product=product,
                date=cal,
                sale_date=uncovered_date,
                invoice_no="1",
                quantity=1,
                unit_mrp=Decimal("100.00"),
                mrp_value=Decimal("100.00"),
                net_value=Decimal("100.00"),
                discount_value=Decimal("0.00"),
            )


@pytest.mark.django_db
def test_ensure_brand_partition_is_idempotent():
    brand = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")

    name_first = ensure_brand_partition(brand.brand_id)
    name_second = ensure_brand_partition(brand.brand_id)

    assert name_first == name_second == f"fact_sales_b{brand.brand_id}"
