import pytest
from django.db import IntegrityError, transaction

from apps.masterdata.models import DimBrand, DimProduct, DimStore


@pytest.mark.django_db
def test_store_code_unique_within_brand_but_not_across_brands():
    killer = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")
    pepe = DimBrand.objects.create(brand_code="PEPE", brand_name="Pepe")

    DimStore.objects.create(brand=killer, store_code="S001", store_name="Killer Store 1")
    # Same store_code under a different brand is fine.
    DimStore.objects.create(brand=pepe, store_code="S001", store_name="Pepe Store 1")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DimStore.objects.create(brand=killer, store_code="S001", store_name="Duplicate")


@pytest.mark.django_db
def test_barcode_unique_within_brand_but_not_across_brands():
    killer = DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")
    pepe = DimBrand.objects.create(brand_code="PEPE", brand_name="Pepe")

    DimProduct.objects.create(brand=killer, barcode="8905646747185")
    DimProduct.objects.create(brand=pepe, barcode="8905646747185")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DimProduct.objects.create(brand=killer, barcode="8905646747185")


@pytest.mark.django_db
def test_brand_code_globally_unique():
    DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DimBrand.objects.create(brand_code="KILLER", brand_name="Duplicate")
