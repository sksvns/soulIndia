from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.masterdata.models import DimCalendar

MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def fiscal_quarter(month_no: int) -> int:
    """Apr-Jun=1, Jul-Sep=2, Oct-Dec=3, Jan-Mar=4."""
    return ((month_no - 4) % 12) // 3 + 1


def financial_year_label(d: date) -> str:
    start_year = d.year if d.month >= 4 else d.year - 1
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


class Command(BaseCommand):
    help = (
        "Seed dim_calendar over a wide date range (covers historical backfill "
        "plus growth runway). Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start", default="2020-04-01", help="YYYY-MM-DD")
        parser.add_argument("--end", default="2031-03-31", help="YYYY-MM-DD")

    def handle(self, *args, **options):
        start = date.fromisoformat(options["start"])
        end = date.fromisoformat(options["end"])

        existing = set(
            DimCalendar.objects.filter(date__range=(start, end)).values_list("date", flat=True)
        )

        rows = []
        current = start
        while current <= end:
            if current not in existing:
                rows.append(
                    DimCalendar(
                        date=current,
                        day=current.day,
                        month_no=current.month,
                        month_name=MONTH_NAMES[current.month - 1],
                        quarter=fiscal_quarter(current.month),
                        financial_year=financial_year_label(current),
                    )
                )
            current += timedelta(days=1)

        with transaction.atomic():
            DimCalendar.objects.bulk_create(rows, batch_size=1000)

        self.stdout.write(f"Seeded {len(rows)} new calendar rows ({start} to {end}).")
