from django.contrib import admin

from .models import (
    AttributeRegistry,
    BrandUploadConfig,
    DimBrand,
    DimCalendar,
    DimProduct,
    DimSeason,
    DimStore,
)


@admin.register(DimBrand)
class DimBrandAdmin(admin.ModelAdmin):
    list_display = ("brand_code", "brand_name", "active", "created_at")
    search_fields = ("brand_code", "brand_name")


@admin.register(BrandUploadConfig)
class BrandUploadConfigAdmin(admin.ModelAdmin):
    list_display = ("brand", "product_line", "name", "date_source", "active")
    list_filter = ("brand", "product_line", "active")


@admin.register(DimStore)
class DimStoreAdmin(admin.ModelAdmin):
    list_display = ("brand", "store_code", "store_name", "city", "state", "zone")
    list_filter = ("brand", "zone", "state")
    search_fields = ("store_code", "store_name", "city")


@admin.register(DimProduct)
class DimProductAdmin(admin.ModelAdmin):
    list_display = ("brand", "barcode", "article_code", "category", "sub_category")
    list_filter = ("brand", "category", "sub_category", "gender")
    search_fields = ("barcode", "article_code")


@admin.register(DimCalendar)
class DimCalendarAdmin(admin.ModelAdmin):
    list_display = ("date", "financial_year", "quarter", "month_name")
    list_filter = ("financial_year", "quarter")
    date_hierarchy = "date"


@admin.register(DimSeason)
class DimSeasonAdmin(admin.ModelAdmin):
    list_display = ("season_code", "season_type", "season_year", "sort_order")


@admin.register(AttributeRegistry)
class AttributeRegistryAdmin(admin.ModelAdmin):
    list_display = (
        "canonical_name",
        "source",
        "is_filterable",
        "is_dimension",
        "data_type",
        "active",
    )
    list_filter = ("is_filterable", "is_dimension", "active")
