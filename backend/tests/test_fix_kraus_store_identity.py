from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.loader import load_batch
from apps.ingestion.models import FactSales, UploadBatch
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimStore
from tests.ingestion_fixtures import KRAUS_GOOD_ROWS, kraus_workbook


@pytest.fixture
def kraus_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KRAUS")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


def _load_a_fake_store_row(brand, config, user, store_name, store_code, invoice_no):
    """Simulates data ingested before apply_store_identity_overrides
    existed: temporarily strips the override so a swapped-column row
    creates a fake DimStore, matching real historical production data."""
    overrides = config.validation_rules.pop("store_identity_overrides")
    config.save(update_fields=["validation_rules"])
    try:
        row = {
            **KRAUS_GOOD_ROWS[0],
            "INVOICE NO": invoice_no,
            "STORE NAME": store_name,
            "STORE CODE": store_code,
        }
        result = run_pipeline(brand, config, kraus_workbook([row]), f"pre_fix_{invoice_no}.xlsx")
        assert result.ok, result.errors
        batch = UploadBatch.objects.create(
            brand=brand,
            config=config,
            uploaded_by=user,
            file_name=f"pre_fix_{invoice_no}.xlsx",
            object_key=f"uploads/kraus/womenswear/pre_fix_{invoice_no}.xlsx",
        )
        load_batch(batch, result.rows)
    finally:
        config.validation_rules["store_identity_overrides"] = overrides
        config.save(update_fields=["validation_rules"])


@pytest.mark.django_db
def test_fix_kraus_store_identity_merges_fake_store_into_the_real_one(
    kraus_brand_and_config, data_inserter_user
):
    brand, config = kraus_brand_and_config
    _load_a_fake_store_row(brand, config, data_inserter_user, "KRA-3", "0202-0016039", 55001)
    fake_store = DimStore.objects.get(brand=brand, store_code="0202-0016039")
    assert fake_store.store_name == "KRA-3"
    assert FactSales.objects.filter(store=fake_store).count() == 1

    out = StringIO()
    call_command("fix_kraus_store_identity", "--yes", stdout=out)

    assert not DimStore.objects.filter(brand=brand, store_code="0202-0016039").exists()
    real_store = DimStore.objects.get(brand=brand, store_code="KRA-3")
    assert real_store.store_name == "THE BOMBAY FASHION"
    assert FactSales.objects.filter(store=real_store).count() == 1
    assert "Repaired: repointed 1 row(s) across 1 fake store(s)" in out.getvalue()


@pytest.mark.django_db
def test_fix_kraus_store_identity_merges_several_fake_stores_for_the_same_real_store(
    kraus_brand_and_config, data_inserter_user
):
    """Two different fake per-row reference numbers, both really KRA-2 --
    must all collapse onto the one real DimStore, not one each."""
    brand, config = kraus_brand_and_config
    _load_a_fake_store_row(brand, config, data_inserter_user, "KRA-2", "CA891", 55002)
    _load_a_fake_store_row(brand, config, data_inserter_user, "KRA-2", "CA9778", 55003)

    call_command("fix_kraus_store_identity", "--yes", stdout=StringIO())

    real_store = DimStore.objects.get(brand=brand, store_code="KRA-2")
    assert real_store.store_name == "DAFTARI TEXTILES PVT LTD"
    assert FactSales.objects.filter(store=real_store).count() == 2
    assert not DimStore.objects.filter(brand=brand, store_code__in=["CA891", "CA9778"]).exists()


@pytest.mark.django_db
def test_fix_kraus_store_identity_dry_run_changes_nothing(
    kraus_brand_and_config, data_inserter_user
):
    brand, config = kraus_brand_and_config
    _load_a_fake_store_row(brand, config, data_inserter_user, "KRA-1", "11009", 55004)

    out = StringIO()
    call_command("fix_kraus_store_identity", stdout=out)

    assert DimStore.objects.filter(brand=brand, store_code="11009").exists()
    assert "Dry run" in out.getvalue()


@pytest.mark.django_db
def test_fix_kraus_store_identity_is_idempotent(kraus_brand_and_config, data_inserter_user):
    brand, config = kraus_brand_and_config
    _load_a_fake_store_row(brand, config, data_inserter_user, "KRA-1", "11009", 55005)

    call_command("fix_kraus_store_identity", "--yes", stdout=StringIO())
    out = StringIO()
    call_command("fix_kraus_store_identity", "--yes", stdout=out)

    assert "Nothing to repair" in out.getvalue()


@pytest.mark.django_db
def test_fix_kraus_store_identity_is_a_noop_when_nothing_is_broken(kraus_brand_and_config):
    brand, config = kraus_brand_and_config

    out = StringIO()
    call_command("fix_kraus_store_identity", "--yes", stdout=out)

    assert "Nothing to repair" in out.getvalue()
