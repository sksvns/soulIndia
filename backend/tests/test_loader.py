from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models import Sum

from apps.ingestion.loader import (
    DataAlterationNotPermitted,
    determine_slices,
    load_batch,
    month_bounds,
    rollback_batch,
)
from apps.ingestion.models import DataAlterationAudit, FactSales, UploadBatch
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand, DimSeason
from tests.ingestion_fixtures import KILLER_GOOD_ROWS, killer_workbook


@pytest.fixture
def killer_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


def _validated_rows(brand, config, rows):
    result = run_pipeline(brand, config, killer_workbook(rows), "test.xlsx")
    assert result.ok, result.errors
    return result.rows


def _make_batch(brand, config, user):
    return UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=user,
        file_name="test.xlsx",
        object_key="uploads/killer/menswear/test.xlsx",
    )


def test_month_bounds_handles_year_rollover():
    assert month_bounds(2023, 4) == (date(2023, 4, 1), date(2023, 5, 1))
    assert month_bounds(2023, 12) == (date(2023, 12, 1), date(2024, 1, 1))
    assert month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 3, 1))  # leap year


def test_determine_slices_groups_by_store_and_calendar_month_not_supplied_text():
    rows = [
        {"store_id": 1, "sale_date": date(2023, 4, 5)},
        {"store_id": 1, "sale_date": date(2023, 4, 20)},
        {"store_id": 1, "sale_date": date(2024, 4, 5)},  # same store, same "APRIL", different year
        {"store_id": 2, "sale_date": date(2023, 4, 5)},
    ]

    slices = determine_slices(rows)

    assert set(slices.keys()) == {(1, 2023, 4), (1, 2024, 4), (2, 2023, 4)}
    assert len(slices[(1, 2023, 4)]) == 2


@pytest.mark.django_db
def test_load_batch_writes_rows_into_fact_sales_with_correct_math(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _make_batch(brand, config, data_inserter_user)
    rows = _validated_rows(brand, config, KILLER_GOOD_ROWS)

    slices = load_batch(batch, rows)

    assert FactSales.objects.filter(batch=batch).count() == 3
    assert sum(s["row_count"] for s in slices) == 3

    sanity_fact = FactSales.objects.get(batch=batch, invoice_no="81")
    assert sanity_fact.unit_mrp == Decimal("2499.00")
    assert sanity_fact.net_value == Decimal("2124.00")
    assert sanity_fact.discount_value == Decimal("375.00")
    assert sanity_fact.is_return is False

    return_fact = FactSales.objects.get(batch=batch, invoice_no="417")
    assert return_fact.is_return is True
    assert return_fact.quantity == -1


@pytest.mark.django_db
def test_load_batch_resolves_season_and_preserves_supplied_text_in_extra(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _make_batch(brand, config, data_inserter_user)
    rows = _validated_rows(brand, config, KILLER_GOOD_ROWS)

    load_batch(batch, rows)

    assert DimSeason.objects.filter(season_code="SS23").exists()
    fact = FactSales.objects.get(batch=batch, invoice_no="81")
    assert fact.season.season_code == "SS23"
    assert fact.extra["supplied_month"] == "APRIL"
    assert fact.extra["supplied_financial_year"] == "23-24"


@pytest.mark.django_db
def test_reuploading_the_same_data_twice_yields_identical_totals(
    killer_brand_and_config, data_inserter_user, super_admin_user
):
    """Acceptance: uploading April twice yields identical totals. The second
    upload replaces existing data (ADR-0003), so it needs a Super Admin --
    the replace mechanics under test here are orthogonal to that rule."""
    brand, config = killer_brand_and_config
    rows = _validated_rows(brand, config, KILLER_GOOD_ROWS)

    batch1 = _make_batch(brand, config, data_inserter_user)
    load_batch(batch1, rows)
    total_after_first = FactSales.objects.filter(brand=brand).aggregate(t=Sum("net_value"))["t"]
    count_after_first = FactSales.objects.filter(brand=brand).count()

    batch2 = _make_batch(brand, config, super_admin_user)
    rows2 = _validated_rows(brand, config, KILLER_GOOD_ROWS)
    load_batch(batch2, rows2)
    total_after_second = FactSales.objects.filter(brand=brand).aggregate(t=Sum("net_value"))["t"]
    count_after_second = FactSales.objects.filter(brand=brand).count()

    assert count_after_second == count_after_first  # no duplicates
    assert total_after_second == total_after_first
    # The second batch's upload fully replaced the first's rows for that slice.
    assert not FactSales.objects.filter(batch=batch1).exists()
    assert FactSales.objects.filter(batch=batch2).count() == count_after_first


@pytest.mark.django_db
def test_correction_to_one_store_does_not_touch_another_store(
    killer_brand_and_config, data_inserter_user, super_admin_user
):
    """Acceptance: a store-only correction changes only that store. The
    correction itself replaces existing data (ADR-0003), so it needs a
    Super Admin -- the store-scoping under test here is orthogonal to that
    rule."""
    brand, config = killer_brand_and_config

    store_a_rows = [{**KILLER_GOOD_ROWS[0], "STORE CODE": "ESIS170", "BILL NO \nINVOICE NO": 1}]
    store_b_rows = [{**KILLER_GOOD_ROWS[0], "STORE CODE": "ESIS999", "BILL NO \nINVOICE NO": 2}]

    batch_a = _make_batch(brand, config, data_inserter_user)
    load_batch(batch_a, _validated_rows(brand, config, store_a_rows))
    batch_b = _make_batch(brand, config, data_inserter_user)
    load_batch(batch_b, _validated_rows(brand, config, store_b_rows))

    # Correction: re-upload store A's April with different numbers.
    corrected_store_a_rows = [
        {
            **KILLER_GOOD_ROWS[0],
            "STORE CODE": "ESIS170",
            "BILL NO \nINVOICE NO": 3,
            "NET \nSALE \nVALUE": 1000,
            "DISCOUNT \nVALUE": 1499,
        }
    ]
    batch_a2 = _make_batch(brand, config, super_admin_user)
    load_batch(batch_a2, _validated_rows(brand, config, corrected_store_a_rows))

    # Store B untouched.
    assert FactSales.objects.filter(batch=batch_b).exists()
    store_b_fact = FactSales.objects.get(batch=batch_b)
    assert store_b_fact.net_value == Decimal("2124.00")

    # Store A replaced with the corrected values, old batch gone.
    assert not FactSales.objects.filter(batch=batch_a).exists()
    store_a_fact = FactSales.objects.get(batch=batch_a2)
    assert store_a_fact.net_value == Decimal("1000.00")


@pytest.mark.django_db
def test_a_return_row_reduces_aggregate_net_sales(killer_brand_and_config, data_inserter_user):
    """Acceptance: a negative row reduces net sales."""
    brand, config = killer_brand_and_config
    batch = _make_batch(brand, config, data_inserter_user)
    rows = _validated_rows(brand, config, KILLER_GOOD_ROWS)

    load_batch(batch, rows)

    total_net = FactSales.objects.filter(brand=brand).aggregate(t=Sum("net_value"))["t"]
    # 2124.00 + 2450.00 + (-1519.00) from the return row in KILLER_GOOD_ROWS
    assert total_net == Decimal("3055.00")


@pytest.mark.django_db
def test_upload_spanning_two_financial_years_creates_both_partitions_and_loads_correctly(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    rows_spanning_fy = [
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2023, 3, 25), "BILL NO \nINVOICE NO": 10},
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2023, 4, 2), "BILL NO \nINVOICE NO": 11},
    ]
    batch = _make_batch(brand, config, data_inserter_user)

    slices = load_batch(batch, _validated_rows(brand, config, rows_spanning_fy))

    assert len(slices) == 2  # March slice and April slice, different FYs
    assert FactSales.objects.filter(batch=batch).count() == 2


@pytest.mark.django_db
def test_rollback_batch_deletes_its_facts_and_marks_status(
    killer_brand_and_config, data_inserter_user, super_admin_user
):
    brand, config = killer_brand_and_config
    batch = _make_batch(brand, config, data_inserter_user)
    rows = _validated_rows(brand, config, KILLER_GOOD_ROWS)
    load_batch(batch, rows)
    assert FactSales.objects.filter(batch=batch).count() == 3

    deleted = rollback_batch(batch, super_admin_user)

    assert deleted == 3
    assert not FactSales.objects.filter(batch=batch).exists()
    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.ROLLED_BACK


@pytest.mark.django_db
def test_rollback_only_deletes_its_own_batch_rows(
    killer_brand_and_config, data_inserter_user, super_admin_user
):
    brand, config = killer_brand_and_config
    batch1 = _make_batch(brand, config, data_inserter_user)
    load_batch(batch1, _validated_rows(brand, config, [KILLER_GOOD_ROWS[0]]))
    other_rows = [{**KILLER_GOOD_ROWS[1], "STORE CODE": "ESIS999"}]
    batch2 = _make_batch(brand, config, data_inserter_user)
    load_batch(batch2, _validated_rows(brand, config, other_rows))

    rollback_batch(batch1, super_admin_user)

    assert not FactSales.objects.filter(batch=batch1).exists()
    assert FactSales.objects.filter(batch=batch2).exists()


@pytest.mark.django_db
def test_admin_rollback_action_rolls_back_loaded_batches_only(
    killer_brand_and_config, data_inserter_user, super_admin_user, client
):
    brand, config = killer_brand_and_config
    loaded_batch = _make_batch(brand, config, data_inserter_user)
    load_batch(loaded_batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))
    # load_batch() only writes fact rows; process_upload_batch (tasks.py) is
    # what marks status=loaded in the real flow -- replicate that here.
    loaded_batch.status = UploadBatch.Status.LOADED
    loaded_batch.save(update_fields=["status"])
    received_batch = _make_batch(brand, config, data_inserter_user)  # never loaded

    client.force_login(super_admin_user)
    response = client.post(
        "/admin/ingestion/uploadbatch/",
        {
            "action": "rollback_selected_batches",
            "_selected_action": [loaded_batch.batch_id, received_batch.batch_id],
        },
        follow=True,
    )

    assert response.status_code == 200
    loaded_batch.refresh_from_db()
    received_batch.refresh_from_db()
    assert loaded_batch.status == UploadBatch.Status.ROLLED_BACK
    assert received_batch.status == UploadBatch.Status.RECEIVED  # untouched, was skipped
    assert not FactSales.objects.filter(batch=loaded_batch).exists()


# --- ADR-0003: altering existing data requires Super Admin ------------------


@pytest.mark.django_db
def test_data_inserter_can_freely_load_into_empty_slices_no_audit_created(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _make_batch(brand, config, data_inserter_user)

    load_batch(batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))

    assert FactSales.objects.filter(batch=batch).count() == 3
    assert DataAlterationAudit.objects.count() == 0


@pytest.mark.django_db
def test_data_inserter_is_blocked_from_replacing_existing_data(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    first_batch = _make_batch(brand, config, data_inserter_user)
    load_batch(first_batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))

    second_batch = _make_batch(brand, config, data_inserter_user)
    with pytest.raises(DataAlterationNotPermitted, match="requires Super Admin access"):
        load_batch(second_batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))

    # Nothing changed -- the original data is exactly as it was.
    assert FactSales.objects.filter(batch=first_batch).count() == 3
    assert not FactSales.objects.filter(batch=second_batch).exists()

    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is False
    assert audit.user == data_inserter_user
    assert audit.action == DataAlterationAudit.Action.REPLACE


@pytest.mark.django_db
def test_super_admin_can_replace_existing_data_and_it_is_audited(
    killer_brand_and_config, data_inserter_user, super_admin_user
):
    brand, config = killer_brand_and_config
    first_batch = _make_batch(brand, config, data_inserter_user)
    load_batch(first_batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))

    second_batch = _make_batch(brand, config, super_admin_user)
    load_batch(second_batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))

    assert not FactSales.objects.filter(batch=first_batch).exists()
    assert FactSales.objects.filter(batch=second_batch).count() == 3

    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is True
    assert audit.user == super_admin_user
    assert audit.action == DataAlterationAudit.Action.REPLACE


@pytest.mark.django_db
def test_data_inserter_is_blocked_from_rolling_back_a_loaded_batch(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    batch = _make_batch(brand, config, data_inserter_user)
    load_batch(batch, _validated_rows(brand, config, KILLER_GOOD_ROWS))

    with pytest.raises(DataAlterationNotPermitted, match="requires Super Admin access"):
        rollback_batch(batch, data_inserter_user)

    assert FactSales.objects.filter(batch=batch).count() == 3  # untouched
    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is False
    assert audit.action == DataAlterationAudit.Action.ROLLBACK
