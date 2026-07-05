from django.db import models

from apps.masterdata.models import DimBrand, DimCalendar, DimProduct, DimSeason, DimStore


class FactSales(models.Model):
    """The partitioned fact table.

    Table is created and altered by hand-written SQL in migrations (see
    0001_create_fact_sales.py) because Django's schema editor has no concept
    of PostgreSQL declarative partitioning -- `managed = False` keeps Django
    from ever trying to run DDL against it. `sale_id` alone is unique (single
    shared sequence across all partitions) and is what Django treats as the
    ORM primary key; the real DB primary key is the composite
    (brand_id, sale_date, sale_id), because PostgreSQL requires a unique
    index on a partitioned table to include every partition-key column at
    every partitioning level (LIST(brand_id), then RANGE(sale_date) within
    each brand). See ADR-0002 for why there is deliberately no
    natural/business-column uniqueness constraint here.
    """

    sale_id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(DimBrand, on_delete=models.DO_NOTHING, db_column="brand_id")
    store = models.ForeignKey(DimStore, on_delete=models.DO_NOTHING, db_column="store_id")
    product = models.ForeignKey(DimProduct, on_delete=models.DO_NOTHING, db_column="product_id")
    date = models.ForeignKey(DimCalendar, on_delete=models.DO_NOTHING, db_column="date_id")
    sale_date = models.DateField()
    season = models.ForeignKey(
        DimSeason, on_delete=models.DO_NOTHING, db_column="season_id", null=True, blank=True
    )
    invoice_no = models.CharField(max_length=64)
    quantity = models.IntegerField()
    unit_mrp = models.DecimalField(max_digits=12, decimal_places=2)
    mrp_value = models.DecimalField(max_digits=14, decimal_places=2)
    net_value = models.DecimalField(max_digits=14, decimal_places=2)
    discount_value = models.DecimalField(max_digits=14, decimal_places=2)
    is_return = models.BooleanField(default=False)
    extra = models.JSONField(default=dict, blank=True)
    # Plain (non-FK) column for now -- upload_batch doesn't exist until Day 4.
    # Day 4 adds the real FK constraint once apps.ingestion.UploadBatch exists.
    upload_batch_id = models.BigIntegerField(null=True, blank=True)
    source_row_no = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = "fact_sales"

    def __str__(self):
        return f"sale#{self.sale_id} brand={self.brand_id} {self.sale_date}"
