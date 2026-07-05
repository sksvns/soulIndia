from django.core.management.base import BaseCommand

from apps.masterdata.models import DimBrand

BRANDS = [
    {"brand_code": "KILLER", "brand_name": "Killer"},
    {"brand_code": "PEPE", "brand_name": "Pepe"},
]


class Command(BaseCommand):
    help = "Seed the initial dim_brand rows. Idempotent."

    def handle(self, *args, **options):
        for row in BRANDS:
            brand, created = DimBrand.objects.get_or_create(
                brand_code=row["brand_code"], defaults={"brand_name": row["brand_name"]}
            )
            self.stdout.write(f"{brand.brand_code}: {'created' if created else 'already exists'}")
