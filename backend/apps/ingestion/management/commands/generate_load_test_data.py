"""Day 11 load test: generates synthetic fact_sales rows at scale via
direct bulk COPY, bypassing the Excel-parse/per-row-validate pipeline
entirely. This is deliberate -- the goal here is measuring query/MV/cache
performance at realistic volume, not re-testing ingestion correctness
(that's Day 5/6's job, already covered by real-file verification). Always
targets a dedicated LOADTEST_* brand; never touches real brand data.

numpy is already a transitive dependency of pandas (requirements.txt), not
a new addition -- used here purely for vectorized random generation, which
is what makes generating tens of millions of rows in a single run
practical at all.
"""

import time
from datetime import date

import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg.types.json import Jsonb

from apps.ingestion.partitioning import ensure_financial_year_partition
from apps.masterdata.models import DimBrand, DimCalendar, DimProduct, DimSeason, DimStore

CATEGORIES = [
    ("SHIRTS", "SHIRTS"),
    ("JEANS", "JEANS"),
    ("T-SHIRTS", "T-SHIRTS"),
    ("TROUSERS", "TROUSERS"),
    ("JACKETS", "JACKETS"),
    ("SWEATERS", "SWEATERS"),
    ("SHORTS", "SHORTS"),
]
SEASON_CODES = ["SS23", "AW23", "SS24", "AW24", "SS25", "AW25", "CORE"]
ZONES = ["EAST", "WEST", "NORTH", "SOUTH"]
CITIES = ["MUMBAI", "DELHI", "BANGALORE", "CHENNAI", "KOLKATA", "PUNE", "HYDERABAD", "PATNA"]
GENDERS = ["MENS", "WOMENS", "KIDS"]

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


class Command(BaseCommand):
    help = (
        "Generates synthetic fact_sales rows at scale for the Day 11 load "
        "test, via direct bulk COPY into a dedicated LOADTEST_* brand. "
        "Never touches real brand data."
    )

    def add_arguments(self, parser):
        parser.add_argument("--brand-code", required=True)
        parser.add_argument("--brand-name", required=True)
        parser.add_argument("--rows", type=int, default=12_000_000)
        parser.add_argument("--stores", type=int, default=300)
        parser.add_argument("--products", type=int, default=8000)
        parser.add_argument("--batch-size", type=int, default=200_000)
        parser.add_argument("--start-year", type=int, default=2023)
        parser.add_argument("--num-years", type=int, default=3)
        parser.add_argument("--seed", type=int, default=None)

    def handle(self, *args, **options):
        if options["seed"] is not None:
            np.random.seed(options["seed"])

        brand_code = options["brand_code"]
        if not brand_code.startswith("LOADTEST"):
            raise CommandError("--brand-code must start with LOADTEST (safety: never real brands)")

        brand, created = DimBrand.objects.get_or_create(
            brand_code=brand_code,
            defaults={"brand_name": options["brand_name"], "active": True},
        )
        if not created:
            brand.active = True
            brand.brand_name = options["brand_name"]
            brand.save(update_fields=["active", "brand_name"])
        self.stdout.write(
            f"Brand {brand.brand_code} (id={brand.brand_id}): "
            f"{'created' if created else 'reused'}"
        )

        stores = self._ensure_stores(brand, options["stores"])
        self.stdout.write(f"Stores: {len(stores)}")
        products = self._ensure_products(brand, options["products"])
        self.stdout.write(f"Products: {len(products)}")
        season_ids = self._ensure_seasons()
        self.stdout.write(f"Seasons: {len(season_ids)}")

        start_year = options["start_year"]
        num_years = options["num_years"]
        for y in range(start_year, start_year + num_years):
            partition = ensure_financial_year_partition(brand.brand_id, y)
            self.stdout.write(f"Partition ready: {partition}")

        date_start = date(start_year, 4, 1)
        date_end = date(start_year + num_years, 4, 1)
        calendar_rows = list(
            DimCalendar.objects.filter(date__gte=date_start, date__lt=date_end)
            .order_by("date")
            .values_list("date", "date_id")
        )
        if not calendar_rows:
            raise CommandError(
                f"No dim_calendar rows in [{date_start}, {date_end}) -- run seed_calendar first"
            )
        dates = [row[0] for row in calendar_rows]
        date_ids = [row[1] for row in calendar_rows]
        self.stdout.write(f"Date range: {dates[0]} to {dates[-1]} ({len(dates)} days)")

        store_ids = np.array([s.store_id for s in stores])
        product_ids = np.array([p.product_id for p in products])
        season_id_arr = np.array(season_ids)

        total_rows = options["rows"]
        batch_size = options["batch_size"]
        inserted = 0
        t0 = time.time()
        offset = 0
        while inserted < total_rows:
            n = min(batch_size, total_rows - inserted)
            self._generate_and_copy_batch(
                brand.brand_id, n, offset, dates, date_ids, store_ids, product_ids, season_id_arr
            )
            inserted += n
            offset += n
            elapsed = time.time() - t0
            rate = inserted / elapsed if elapsed > 0 else 0
            self.stdout.write(
                f"  {inserted:,}/{total_rows:,} rows "
                f"({rate:,.0f} rows/sec, {elapsed:.1f}s elapsed)"
            )

        elapsed = time.time() - t0
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {inserted:,} rows for {brand.brand_code} in {elapsed:.1f}s "
                f"({inserted / elapsed:,.0f} rows/sec)"
            )
        )

    def _ensure_stores(self, brand, count):
        existing = list(DimStore.objects.filter(brand=brand))
        if len(existing) >= count:
            return existing[:count]
        rng = np.random.default_rng()
        to_create = []
        for i in range(len(existing), count):
            city_idx = rng.integers(0, len(CITIES))
            to_create.append(
                DimStore(
                    brand=brand,
                    store_code=f"LT{i:05d}",
                    store_name=f"Load Test Store {i}",
                    city=CITIES[city_idx],
                    state="SYNTHETIC",
                    zone=ZONES[city_idx % len(ZONES)],
                    store_type="SALE",
                )
            )
        DimStore.objects.bulk_create(to_create, batch_size=5000)
        return list(DimStore.objects.filter(brand=brand))

    def _ensure_products(self, brand, count):
        existing = list(DimProduct.objects.filter(brand=brand))
        if len(existing) >= count:
            return existing[:count]
        rng = np.random.default_rng()
        to_create = []
        for i in range(len(existing), count):
            cat_idx = rng.integers(0, len(CATEGORIES))
            category, sub_category = CATEGORIES[cat_idx]
            to_create.append(
                DimProduct(
                    brand=brand,
                    barcode=f"9{brand.brand_id:03d}{i:010d}",
                    article_code=f"LT-ART-{i}",
                    category=category,
                    sub_category=sub_category,
                    gender=GENDERS[i % len(GENDERS)],
                    size="M",
                )
            )
        DimProduct.objects.bulk_create(to_create, batch_size=5000)
        return list(DimProduct.objects.filter(brand=brand))

    def _ensure_seasons(self):
        ids = []
        for code in SEASON_CODES:
            season, _ = DimSeason.objects.get_or_create(
                season_code=code, defaults={"season_type": "SYNTHETIC"}
            )
            ids.append(season.season_id)
        return ids

    def _generate_and_copy_batch(
        self, brand_id, n, offset, dates, date_ids, store_ids, product_ids, season_ids
    ):
        rng = np.random.default_rng()
        date_idx = rng.integers(0, len(dates), n)
        store_id_batch = rng.choice(store_ids, n)
        product_id_batch = rng.choice(product_ids, n)
        season_id_batch = rng.choice(season_ids, n)
        quantity = rng.choice(np.array([1, 1, 1, 1, 1, 2, 2, 3], dtype=np.int64), n).astype(
            np.int64
        )
        is_return = rng.random(n) < 0.02
        unit_mrp = rng.integers(299, 4999, n).astype(np.float64)
        discount_pct = rng.uniform(0, 45, n)

        mrp_value = unit_mrp * quantity
        net_value = mrp_value * (1 - discount_pct / 100)
        discount_value = mrp_value - net_value

        quantity = np.where(is_return, -quantity, quantity)
        mrp_value = np.where(is_return, -mrp_value, mrp_value)
        net_value = np.where(is_return, -net_value, net_value)
        discount_value = np.where(is_return, -discount_value, discount_value)

        unit_mrp = unit_mrp.round(2)
        mrp_value = mrp_value.round(2)
        net_value = net_value.round(2)
        discount_value = discount_value.round(2)

        quantity_list = quantity.tolist()
        unit_mrp_list = unit_mrp.tolist()
        mrp_value_list = mrp_value.tolist()
        net_value_list = net_value.tolist()
        discount_value_list = discount_value.tolist()
        is_return_list = is_return.tolist()
        store_id_list = store_id_batch.tolist()
        product_id_list = product_id_batch.tolist()
        season_id_list = season_id_batch.tolist()

        copy_sql = f"COPY fact_sales ({', '.join(STAGING_COLUMNS)}) FROM STDIN"
        with connection.cursor() as cursor:
            with cursor.copy(copy_sql) as copy:
                for i in range(n):
                    di = date_idx[i]
                    copy.write_row(
                        [
                            brand_id,
                            store_id_list[i],
                            product_id_list[i],
                            date_ids[di],
                            dates[di],
                            season_id_list[i],
                            f"LT-{brand_id}-{offset + i}",
                            quantity_list[i],
                            unit_mrp_list[i],
                            mrp_value_list[i],
                            net_value_list[i],
                            discount_value_list[i],
                            is_return_list[i],
                            Jsonb({}),
                            None,
                            None,
                        ]
                    )
