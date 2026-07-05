from django.core.management.base import BaseCommand

from apps.masterdata.models import AttributeRegistry

# (canonical_name, source, is_dimension, data_type). Every entry here is
# filterable -- this is what the Day 8 filter engine reads to build queries,
# so a new filterable attribute becomes a row here (+ optional index), not a
# code change.
ATTRIBUTES = [
    ("brand", "dim_brand.brand_code", True, "text"),
    ("store", "dim_store.store_code", True, "text"),
    ("city", "dim_store.city", True, "text"),
    ("zone", "dim_store.zone", True, "text"),
    ("category", "dim_product.category", True, "text"),
    ("sub_category", "dim_product.sub_category", True, "text"),
    ("gender", "dim_product.gender", True, "text"),
    ("color", "dim_product.color", True, "text"),
    ("fit", "dim_product.fit", True, "text"),
    ("size", "dim_product.size", True, "text"),
    ("season", "dim_season.season_code", True, "text"),
    ("financial_year", "dim_calendar.financial_year", True, "text"),
    ("month", "dim_calendar.month_name", True, "text"),
    (
        "discount_range",
        "fact_sales.discount_pct (computed, bucketed in materialized views)",
        False,
        "numeric_range",
    ),
]


class Command(BaseCommand):
    help = "Seed the Phase-1 canonical filterable attributes. Idempotent."

    def handle(self, *args, **options):
        for canonical_name, source, is_dimension, data_type in ATTRIBUTES:
            AttributeRegistry.objects.update_or_create(
                canonical_name=canonical_name,
                defaults={
                    "source": source,
                    "is_filterable": True,
                    "is_dimension": is_dimension,
                    "data_type": data_type,
                    "active": True,
                },
            )
        self.stdout.write(f"Seeded {len(ATTRIBUTES)} attribute_registry rows")
