from django.db import models


class DimBrand(models.Model):
    brand_id = models.BigAutoField(primary_key=True)
    brand_code = models.CharField(max_length=32, unique=True)
    brand_name = models.CharField(max_length=128)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dim_brand"

    def __str__(self):
        return self.brand_code


class BrandUploadConfig(models.Model):
    """Maps a (brand, product_line)'s source columns to canonical fields.

    Not versioned over time -- file formats are stable per the client, so
    each (brand, product_line) has exactly one active config.
    """

    config_id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(DimBrand, on_delete=models.PROTECT, related_name="upload_configs")
    product_line = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    column_map = models.JSONField()
    date_source = models.CharField(max_length=64)
    validation_rules = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "brand_upload_config"
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "product_line"], name="uniq_brand_product_line_config"
            ),
        ]

    def __str__(self):
        return f"{self.brand.brand_code}/{self.product_line}"


class DimStore(models.Model):
    store_id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(DimBrand, on_delete=models.PROTECT, related_name="stores")
    store_code = models.CharField(max_length=32)
    store_name = models.CharField(max_length=255)
    city = models.CharField(max_length=128, blank=True, null=True)
    state = models.CharField(max_length=128, blank=True, null=True)
    zone = models.CharField(max_length=64, blank=True, null=True)
    store_type = models.CharField(max_length=64, blank=True, null=True)
    distributor_name = models.CharField(max_length=255, blank=True, null=True)
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dim_store"
        constraints = [
            models.UniqueConstraint(fields=["brand", "store_code"], name="uniq_brand_store_code"),
        ]

    def __str__(self):
        return f"{self.brand.brand_code}/{self.store_code}"


class DimProduct(models.Model):
    product_id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(DimBrand, on_delete=models.PROTECT, related_name="products")
    barcode = models.CharField(max_length=64)
    article_code = models.CharField(max_length=128, blank=True, null=True)
    category = models.CharField(max_length=128, blank=True, null=True)
    sub_category = models.CharField(max_length=128, blank=True, null=True)
    gender = models.CharField(max_length=32, blank=True, null=True)
    fit = models.CharField(max_length=64, blank=True, null=True)
    color = models.CharField(max_length=64, blank=True, null=True)
    size = models.CharField(max_length=32, blank=True, null=True)
    print_type = models.CharField(max_length=64, blank=True, null=True)
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dim_product"
        constraints = [
            models.UniqueConstraint(fields=["brand", "barcode"], name="uniq_brand_barcode"),
        ]

    def __str__(self):
        return f"{self.brand.brand_code}/{self.barcode}"


class DimCalendar(models.Model):
    date_id = models.BigAutoField(primary_key=True)
    date = models.DateField(unique=True)
    day = models.PositiveSmallIntegerField()
    month_no = models.PositiveSmallIntegerField()
    month_name = models.CharField(max_length=16)
    quarter = models.PositiveSmallIntegerField(help_text="Fiscal quarter: Apr-Jun=1 .. Jan-Mar=4")
    financial_year = models.CharField(max_length=8, help_text="e.g. '23-24', Apr-Mar")

    class Meta:
        db_table = "dim_calendar"

    def __str__(self):
        return self.date.isoformat()


class DimSeason(models.Model):
    """Season values as supplied by brands, trusted as-is -- never derived from the date."""

    season_id = models.BigAutoField(primary_key=True)
    season_code = models.CharField(max_length=64, unique=True)
    season_type = models.CharField(max_length=32, blank=True, null=True)
    season_year = models.PositiveSmallIntegerField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "dim_season"

    def __str__(self):
        return self.season_code


class AttributeRegistry(models.Model):
    """Declares which canonical attributes the filter/analytics layer exposes."""

    attr_id = models.BigAutoField(primary_key=True)
    canonical_name = models.CharField(max_length=64, unique=True)
    source = models.CharField(max_length=255)
    is_filterable = models.BooleanField(default=True)
    is_dimension = models.BooleanField(default=True)
    data_type = models.CharField(max_length=32)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "attribute_registry"

    def __str__(self):
        return self.canonical_name
