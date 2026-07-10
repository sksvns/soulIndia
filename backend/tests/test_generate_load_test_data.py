from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.ingestion.models import FactSales
from apps.masterdata.models import DimBrand, DimProduct, DimStore


@pytest.mark.django_db
def test_generate_load_test_data_creates_dims_and_facts(seed_calendar):
    call_command(
        "generate_load_test_data",
        "--brand-code=LOADTEST_UNITTEST",
        "--brand-name=Load Test Unit Test",
        "--rows=1000",
        "--stores=5",
        "--products=20",
        "--batch-size=400",
        "--start-year=2023",
        "--num-years=1",
        "--seed=1",
        stdout=StringIO(),
    )

    brand = DimBrand.objects.get(brand_code="LOADTEST_UNITTEST")
    assert brand.active is True
    assert DimStore.objects.filter(brand=brand).count() == 5
    assert DimProduct.objects.filter(brand=brand).count() == 20

    facts = FactSales.objects.filter(brand=brand)
    assert facts.count() == 1000

    # Returns are signed consistently: quantity/mrp/net/discount all
    # negative together, matching the real-data convention (ADR-0004).
    for row in facts.filter(is_return=True)[:20]:
        assert row.quantity < 0
        assert row.mrp_value < 0
        assert row.net_value < 0
        assert row.unit_mrp > 0

    for row in facts.filter(is_return=False)[:20]:
        assert row.quantity > 0
        assert row.mrp_value > 0

    # mrp_value = unit_mrp * quantity holds exactly for synthetic data
    # (unlike real EOSS-priced data, per Day 5's finding) since it's
    # generated that way on purpose -- signed quantity, so this holds for
    # returns too (negative * positive = negative, matching mrp_value).
    sample = facts.first()
    assert sample.mrp_value == sample.unit_mrp * sample.quantity


@pytest.mark.django_db
def test_generate_load_test_data_rejects_non_loadtest_brand_code(seed_calendar):
    with pytest.raises(CommandError, match="LOADTEST"):
        call_command(
            "generate_load_test_data",
            "--brand-code=KILLER",
            "--brand-name=Not Allowed",
            "--rows=10",
            stdout=StringIO(),
        )


@pytest.mark.django_db
def test_generate_load_test_data_is_additive_on_rerun(seed_calendar):
    """Re-running with more rows appends rather than duplicating
    dimensions -- stores/products are reused, not recreated."""
    call_command(
        "generate_load_test_data",
        "--brand-code=LOADTEST_RERUN",
        "--brand-name=Load Test Rerun",
        "--rows=200",
        "--stores=3",
        "--products=10",
        "--batch-size=200",
        "--num-years=1",
        stdout=StringIO(),
    )
    call_command(
        "generate_load_test_data",
        "--brand-code=LOADTEST_RERUN",
        "--brand-name=Load Test Rerun",
        "--rows=200",
        "--stores=3",
        "--products=10",
        "--batch-size=200",
        "--num-years=1",
        stdout=StringIO(),
    )

    brand = DimBrand.objects.get(brand_code="LOADTEST_RERUN")
    assert DimStore.objects.filter(brand=brand).count() == 3
    assert DimProduct.objects.filter(brand=brand).count() == 10
    assert FactSales.objects.filter(brand=brand).count() == 400
