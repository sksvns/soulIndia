import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.masterdata.models import BrandUploadConfig, DimBrand

SEED_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "seed_data"
CONFIG_FILES = [
    "killer_menswear.json",
    "pepe_menswear.json",
    "junior_killer_kids.json",
    "kraus_womenswear.json",
]


class Command(BaseCommand):
    help = (
        "Load the per-(brand,product_line) upload mapping configs from "
        "seed_data/*.json (see docs/schema.md). Idempotent -- run seed_brands "
        "first."
    )

    def handle(self, *args, **options):
        for filename in CONFIG_FILES:
            data = json.loads((SEED_DATA_DIR / filename).read_text())
            brand_code = data["brand_code"]

            try:
                brand = DimBrand.objects.get(brand_code=brand_code)
            except DimBrand.DoesNotExist as exc:
                raise CommandError(
                    f"Brand '{brand_code}' does not exist -- run seed_brands first"
                ) from exc

            # The canonical schema (plan.md Sec 3) only gives brand_upload_config
            # three knobs: column_map, date_source, validation_rules. Anything
            # in the Day 0 JSON that isn't a plain column mapping -- Pepe's
            # financial_year derived-exception spec, the documented list of
            # known/expected extra columns -- folds into validation_rules
            # rather than needing a schema change.
            validation_rules = dict(data.get("validation_rules", {}))
            if "financial_year" in data:
                validation_rules["derived_fields"] = {"financial_year": data["financial_year"]}
            if "extra_source_columns" in data:
                validation_rules["extra_source_columns"] = data["extra_source_columns"]
            if "sheet_name" in data:
                validation_rules["sheet_name"] = data["sheet_name"]

            _config, created = BrandUploadConfig.objects.update_or_create(
                brand=brand,
                product_line=data["product_line"],
                defaults={
                    "name": f"{brand_code} {data['product_line']}",
                    "column_map": data["column_map"],
                    "date_source": data["date_source"],
                    "validation_rules": validation_rules,
                    "active": True,
                },
            )
            verb = "created" if created else "updated"
            self.stdout.write(f"{brand_code}/{data['product_line']}: {verb}")
