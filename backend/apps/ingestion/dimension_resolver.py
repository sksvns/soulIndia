"""Phase B: bulk resolve-or-create for dim_store/dim_product. Only runs
after Phase A validation has fully passed for the whole file (see
validation.py) -- "new product-line values are auto-created as dimension
rows during load, zero code changes" (docs/architecture.md, extensibility
principle), but only for files that are otherwise clean.
"""

from apps.masterdata.models import DimProduct, DimStore


def resolve_stores(brand, rows: list[dict]) -> dict[str, int]:
    codes = {r["store_code"] for r in rows if r.get("store_code")}
    existing = {
        s.store_code: s.store_id for s in DimStore.objects.filter(brand=brand, store_code__in=codes)
    }

    missing = codes - existing.keys()
    if missing:
        first_row_by_code = {}
        for row in rows:
            code = row.get("store_code")
            if code in missing and code not in first_row_by_code:
                first_row_by_code[code] = row

        DimStore.objects.bulk_create(
            [
                DimStore(
                    brand=brand,
                    store_code=code,
                    store_name=row.get("store_name") or code,
                    city=row.get("city"),
                    state=row.get("state"),
                    zone=row.get("zone"),
                    store_type=row.get("store_type"),
                    distributor_name=row.get("distributor_name"),
                )
                for code, row in first_row_by_code.items()
            ]
        )
        existing.update(
            {
                s.store_code: s.store_id
                for s in DimStore.objects.filter(brand=brand, store_code__in=missing)
            }
        )
    return existing


def resolve_products(brand, rows: list[dict]) -> dict[str, int]:
    barcodes = {r["barcode"] for r in rows if r.get("barcode")}
    existing = {
        p.barcode: p.product_id
        for p in DimProduct.objects.filter(brand=brand, barcode__in=barcodes)
    }

    missing = barcodes - existing.keys()
    if missing:
        first_row_by_barcode = {}
        for row in rows:
            barcode = row.get("barcode")
            if barcode in missing and barcode not in first_row_by_barcode:
                first_row_by_barcode[barcode] = row

        DimProduct.objects.bulk_create(
            [
                DimProduct(
                    brand=brand,
                    barcode=barcode,
                    article_code=row.get("article_code"),
                    category=row.get("category"),
                    sub_category=row.get("sub_category"),
                    gender=row.get("gender"),
                    fit=row.get("fit"),
                    color=row.get("color"),
                    size=row.get("size"),
                    print_type=row.get("print_type"),
                )
                for barcode, row in first_row_by_barcode.items()
            ]
        )
        existing.update(
            {
                p.barcode: p.product_id
                for p in DimProduct.objects.filter(brand=brand, barcode__in=missing)
            }
        )
    return existing
