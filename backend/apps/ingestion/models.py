from django.conf import settings
from django.db import models

from apps.masterdata.models import (
    BrandUploadConfig,
    DimBrand,
    DimCalendar,
    DimProduct,
    DimSeason,
    DimStore,
)


class UploadBatch(models.Model):
    """One uploaded file's provenance and lifecycle.

    `slices` records which (store, month) pairs this batch touched -- see
    ADR-0002 -- which is what the Day 6 loader iterates over, what targets
    MV refresh, and what a rollback undoes.
    """

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PARSING = "parsing", "Parsing"
        VALIDATING = "validating", "Validating"
        FAILED = "failed", "Failed"
        LOADED = "loaded", "Loaded"
        ROLLED_BACK = "rolled_back", "Rolled back"

    batch_id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(DimBrand, on_delete=models.PROTECT, related_name="upload_batches")
    config = models.ForeignKey(
        BrandUploadConfig, on_delete=models.PROTECT, related_name="upload_batches"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="upload_batches"
    )
    file_name = models.CharField(max_length=255)
    object_key = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    row_count = models.IntegerField(null=True, blank=True)
    error_count = models.IntegerField(null=True, blank=True)
    slices = models.JSONField(default=list, blank=True)
    error_report_key = models.CharField(max_length=512, null=True, blank=True)
    # Set only for system-level failures (storage/DB errors, bugs) -- row-level
    # data-quality failures use error_count + error_report_key instead. Exists
    # so a batch can never go silently stuck: every failure is visible with a
    # reason, whether it's bad data or a system fault.
    failure_reason = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "upload_batch"
        permissions = [
            (
                "alter_existing_data",
                "Can replace or roll back sales data that is already loaded",
            ),
        ]

    def __str__(self):
        return f"batch#{self.batch_id} {self.brand.brand_code} {self.status}"


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
    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.DO_NOTHING,
        db_column="upload_batch_id",
        null=True,
        blank=True,
        related_name="fact_rows",
    )
    source_row_no = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = "fact_sales"

    def __str__(self):
        return f"sale#{self.sale_id} brand={self.brand_id} {self.sale_date}"


class DataAlterationAudit(models.Model):
    """Every attempt to replace, roll back, or filter-delete already-loaded
    sales data -- allowed or blocked. `ingestion.alter_existing_data` is the
    capability that gates this (Super Admin has it, since seed_roles gives
    Super Admin every permission that exists; Data Inserter does not, since
    it's not on that role's curated allowlist). A fresh load into empty
    slices is never audited here -- only genuine alterations of existing
    rows.

    `batch` is nullable because a filter-based delete (brand + product_line
    + financial_year + month, from the Delete Data page) can span every
    batch that ever loaded into that slice, not just one -- there's no
    single UploadBatch to point at, so the filter criteria and affected row
    count live in `details` instead.
    """

    class Action(models.TextChoices):
        REPLACE = "replace", "Replace existing slice(s)"
        ROLLBACK = "rollback", "Roll back batch"
        DELETE_FILTERED = "delete_filtered", "Delete by brand/product line/month/year filter"

    audit_id = models.BigAutoField(primary_key=True)
    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name="alteration_audits",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="alteration_audits"
    )
    brand = models.ForeignKey(DimBrand, on_delete=models.PROTECT)
    action = models.CharField(max_length=16, choices=Action.choices)
    details = models.JSONField(default=dict, blank=True)
    allowed = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_alteration_audit"

    def __str__(self):
        verb = "allowed" if self.allowed else "BLOCKED"
        return (
            f"{verb} {self.action}: {self.user} on {self.brand.brand_code} (batch #{self.batch_id})"
        )
