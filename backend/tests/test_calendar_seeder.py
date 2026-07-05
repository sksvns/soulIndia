from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from apps.masterdata.models import DimBrand, DimCalendar


@pytest.mark.django_db
def test_seed_calendar_covers_range_with_correct_fy_and_quarter():
    call_command("seed_calendar", "--start=2023-04-01", "--end=2023-04-30", stdout=StringIO())

    assert DimCalendar.objects.count() == 30

    apr_5 = DimCalendar.objects.get(date=date(2023, 4, 5))
    assert apr_5.financial_year == "23-24"
    assert apr_5.quarter == 1
    assert apr_5.month_name == "April"

    jan_1_row = DimCalendar.objects.create(
        date=date(2024, 1, 1),
        day=1,
        month_no=1,
        month_name="January",
        quarter=4,
        financial_year="23-24",
    )
    assert jan_1_row.financial_year == "23-24"


@pytest.mark.django_db
def test_seed_calendar_is_idempotent():
    call_command("seed_calendar", "--start=2023-04-01", "--end=2023-04-05", stdout=StringIO())
    call_command("seed_calendar", "--start=2023-04-01", "--end=2023-04-05", stdout=StringIO())

    assert DimCalendar.objects.count() == 5


@pytest.mark.django_db
def test_seed_brands_creates_killer_and_pepe_idempotently():
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_brands", stdout=StringIO())

    assert DimBrand.objects.count() == 2
    assert set(DimBrand.objects.values_list("brand_code", flat=True)) == {"KILLER", "PEPE"}
