"""One-time repair for Kraus DimStore rows created before
apps.ingestion.derivations.apply_store_identity_overrides existed
(2026-09-12). Some of Kraus's real exports put the KRA-x tier code under
STORE NAME instead of STORE CODE, with an unrelated, non-identifying
per-row reference number in the other column -- every ingestion before
the fix took STORE CODE at face value regardless, fracturing what are
really just 3 physical stores (KRA-1/PANKH, KRA-2/DAFTARI TEXTILES PVT
LTD, KRA-3/THE BOMBAY FASHION) into hundreds of fake ones.

For every already-ingested fake DimStore row (store_name is one of the
3 real names but store_code isn't the matching KRA-x code itself),
repoints every fact_sales row referencing it to the correct canonical
DimStore, then deletes the now-orphaned fake row. Idempotent -- re-
running finds nothing left to repair.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.analytics import cache as analytics_cache
from apps.analytics.materialized_views import refresh_all
from apps.ingestion.models import FactSales
from apps.masterdata.models import DimBrand, DimStore

STORE_IDENTITY_OVERRIDES = {
    "KRA-1": "PANKH",
    "KRA-2": "DAFTARI TEXTILES PVT LTD",
    "KRA-3": "THE BOMBAY FASHION",
}


class Command(BaseCommand):
    help = (
        "One-time repair: merge Kraus's fake per-invoice 'stores' into the 3 real "
        "stores, repointing fact_sales rows and deleting the orphaned duplicates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true", help="Actually apply the fix (dry-run otherwise)."
        )

    def handle(self, *args, **options):
        try:
            brand = DimBrand.objects.get(brand_code="KRAUS")
        except DimBrand.DoesNotExist:
            raise CommandError("No KRAUS brand found.")

        canonical = {}
        for code, name in STORE_IDENTITY_OVERRIDES.items():
            store, _ = DimStore.objects.get_or_create(
                brand=brand, store_code=code, defaults={"store_name": name}
            )
            if store.store_name != name:
                store.store_name = name
                store.save(update_fields=["store_name"])
            canonical[code] = store

        # A fake row (per the actual production bug) has the tier code
        # itself sitting in store_name -- e.g. store_code="0202-0016039",
        # store_name="KRA-3" -- never the other way around, since a
        # correctly-resolved row's store_name is always the real name
        # ("THE BOMBAY FASHION"), which never equals a tier code.
        fake_stores = list(
            DimStore.objects.filter(brand=brand, store_name__in=STORE_IDENTITY_OVERRIDES.keys())
        )

        if not fake_stores:
            self.stdout.write(
                self.style.SUCCESS("Nothing to repair -- no fake Kraus stores found.")
            )
            return

        total_rows = 0
        for fake in fake_stores:
            target = canonical[fake.store_name]
            row_count = FactSales.objects.filter(store=fake).count()
            verb = "Repointing" if options["yes"] else "Would repoint"
            self.stdout.write(
                f"{verb} {row_count} row(s) from fake store {fake.store_code!r} "
                f"({fake.store_name}) -> {target.store_code} ({target.store_name})"
            )
            total_rows += row_count

        self.stdout.write(
            f"{len(fake_stores)} fake store(s), {total_rows} fact_sales row(s) total."
        )

        if not options["yes"]:
            self.stdout.write(self.style.WARNING("Dry run -- re-run with --yes to apply."))
            return

        with transaction.atomic():
            for fake in fake_stores:
                target = canonical[fake.store_name]
                FactSales.objects.filter(store=fake).update(store=target)
                fake.delete()

        refresh_all()
        analytics_cache.bust(brand.brand_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Repaired: repointed {total_rows} row(s) across {len(fake_stores)} fake store(s)."
            )
        )
