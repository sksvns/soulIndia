from io import StringIO

import pytest
from django.core.management import call_command

from apps.masterdata.models import AttributeRegistry, BrandUploadConfig, DimBrand


@pytest.mark.django_db
def test_seed_upload_configs_loads_killer_and_pepe():
    call_command("seed_brands", stdout=StringIO())

    call_command("seed_upload_configs", stdout=StringIO())

    assert BrandUploadConfig.objects.count() == 2

    killer_config = BrandUploadConfig.objects.get(brand__brand_code="KILLER")
    assert killer_config.product_line == "menswear"
    assert killer_config.date_source == "NEW DATE"
    assert killer_config.column_map["sale_date"]["source"] == ["NEW DATE"]
    assert killer_config.column_map["barcode"]["source"] == ["NEW EAN CODE", "EAN CODE"]

    pepe_config = BrandUploadConfig.objects.get(brand__brand_code="PEPE")
    assert pepe_config.date_source == "DATE"
    # The financial_year derived-exception spec has no dedicated column on
    # brand_upload_config -- it folds into validation_rules instead.
    assert (
        pepe_config.validation_rules["derived_fields"]["financial_year"]["derived_from"] == "MONTH"
    )
    assert "WEARHOUSE" in pepe_config.validation_rules["extra_source_columns"]


@pytest.mark.django_db
def test_seed_upload_configs_is_idempotent():
    call_command("seed_brands", stdout=StringIO())

    call_command("seed_upload_configs", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())

    assert BrandUploadConfig.objects.count() == 2


@pytest.mark.django_db
def test_seed_upload_configs_requires_brand_to_exist_first():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("seed_upload_configs", stdout=StringIO())

    assert DimBrand.objects.count() == 0


@pytest.mark.django_db
def test_seed_attribute_registry_covers_phase1_filterable_attributes():
    call_command("seed_attribute_registry", stdout=StringIO())

    names = set(AttributeRegistry.objects.values_list("canonical_name", flat=True))
    expected = {
        "brand",
        "store",
        "city",
        "zone",
        "category",
        "sub_category",
        "gender",
        "color",
        "fit",
        "size",
        "season",
        "financial_year",
        "month",
        "discount_range",
    }
    assert expected <= names
    assert (
        AttributeRegistry.objects.filter(canonical_name="discount_range").get().is_dimension
        is False
    )


@pytest.mark.django_db
def test_seed_attribute_registry_is_idempotent():
    call_command("seed_attribute_registry", stdout=StringIO())
    count_first = AttributeRegistry.objects.count()

    call_command("seed_attribute_registry", stdout=StringIO())

    assert AttributeRegistry.objects.count() == count_first
