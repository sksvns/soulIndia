from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.ingestion.loader import (
    DataAlterationNotPermitted,
    delete_by_filter,
    months_with_data,
    preview_delete,
)
from apps.ingestion.models import DataAlterationAudit, FactSales, UploadBatch
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand
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


def _load(brand, config, user, rows, filename="test.xlsx"):
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=user,
        file_name=filename,
        object_key=f"uploads/{brand.brand_code}/{config.product_line}/{filename}",
    )
    from apps.ingestion.loader import load_batch

    load_batch(batch, _validated_rows(brand, config, rows))
    return batch


@pytest.mark.django_db
def test_delete_by_filter_removes_all_matching_rows_and_returns_count(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    _load(brand, config, super_admin_user, KILLER_GOOD_ROWS)  # all April 2023, FY 23-24
    assert FactSales.objects.filter(brand=brand).count() == 3

    deleted = delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    assert deleted == 3
    assert not FactSales.objects.filter(brand=brand).exists()


@pytest.mark.django_db
def test_delete_by_filter_does_not_touch_a_different_month(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    april_rows = [{**KILLER_GOOD_ROWS[0], "BILL NO \nINVOICE NO": 1}]
    march_rows = [
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2023, 3, 25), "BILL NO \nINVOICE NO": 2}
    ]
    _load(brand, config, super_admin_user, april_rows, "april.xlsx")
    _load(brand, config, super_admin_user, march_rows, "march.xlsx")
    assert FactSales.objects.filter(brand=brand).count() == 2

    deleted = delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    assert deleted == 1
    remaining = FactSales.objects.get(brand=brand)
    assert remaining.sale_date == date(2023, 3, 25)


@pytest.mark.django_db
def test_delete_by_filter_does_not_touch_a_different_brand(
    killer_brand_and_config, super_admin_user
):
    from tests.ingestion_fixtures import JUNIOR_KILLER_GOOD_ROWS, junior_killer_workbook

    brand, config = killer_brand_and_config
    _load(brand, config, super_admin_user, KILLER_GOOD_ROWS)

    jk_brand = DimBrand.objects.get(brand_code="JUNIOR_KILLER")
    jk_config = BrandUploadConfig.objects.get(brand=jk_brand)
    jk_result = run_pipeline(
        jk_brand, jk_config, junior_killer_workbook(JUNIOR_KILLER_GOOD_ROWS), "jk.xlsx"
    )
    assert jk_result.ok, jk_result.errors
    jk_batch = UploadBatch.objects.create(
        brand=jk_brand,
        config=jk_config,
        uploaded_by=super_admin_user,
        file_name="jk.xlsx",
        object_key="uploads/jk/kids/jk.xlsx",
    )
    from apps.ingestion.loader import load_batch

    load_batch(jk_batch, jk_result.rows)
    assert FactSales.objects.filter(brand=jk_brand).exists()

    delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    assert not FactSales.objects.filter(brand=brand).exists()
    assert FactSales.objects.filter(brand=jk_brand).exists()  # untouched


@pytest.mark.django_db
def test_delete_by_filter_scopes_by_product_line_not_just_brand(
    killer_brand_and_config, super_admin_user
):
    """product_line lives on BrandUploadConfig, not fact_sales directly --
    this proves two configs sharing one brand are scoped independently via
    batch -> config.product_line, the same design used for a future brand
    that gains a second product line rather than a whole new brand code."""
    brand, config = killer_brand_and_config
    footwear_config = BrandUploadConfig.objects.create(
        brand=brand,
        product_line="footwear",
        name="Killer Footwear",
        column_map=config.column_map,
        date_source=config.date_source,
        validation_rules=config.validation_rules,
    )
    _load(brand, config, super_admin_user, KILLER_GOOD_ROWS, "menswear.xlsx")
    # Different store code -- a real second product line under one brand
    # can't share a store code with the first (DimStore is unique per
    # (brand, store_code), same reason Pepe Kids became its own brand
    # rather than a product_line under Pepe); this keeps the two configs'
    # (store, month) slices from colliding under ADR-0003's replace check,
    # which is scoped by store, not product_line.
    footwear_rows = [
        {**KILLER_GOOD_ROWS[0], "STORE CODE": "ESIS999", "BILL NO \nINVOICE NO": 999}
    ]
    _load(brand, footwear_config, super_admin_user, footwear_rows, "footwear.xlsx")
    assert FactSales.objects.filter(brand=brand).count() == 4

    deleted = delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    assert deleted == 3
    remaining = FactSales.objects.filter(brand=brand)
    assert remaining.count() == 1
    assert remaining.first().invoice_no == "999"


@pytest.mark.django_db
def test_preview_delete_matches_what_delete_by_filter_actually_removes(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    _load(brand, config, super_admin_user, KILLER_GOOD_ROWS)

    preview = preview_delete(brand, "menswear", "23-24", [4])

    assert preview["row_count"] == 3
    assert preview["store_count"] == 1
    assert preview["total_net_value"] == Decimal("3055.00")  # 2124 + 2450 - 1519 (return)
    assert preview["min_date"] == date(2023, 4, 5)
    assert preview["max_date"] == date(2023, 4, 26)

    deleted = delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)
    assert deleted == preview["row_count"]


@pytest.mark.django_db
def test_preview_delete_returns_zero_row_count_and_null_aggregates_for_no_match(
    killer_brand_and_config,
):
    brand, config = killer_brand_and_config

    preview = preview_delete(brand, "menswear", "23-24", [4])

    assert preview["row_count"] == 0
    assert preview["store_count"] == 0
    assert preview["total_net_value"] is None
    assert preview["min_date"] is None
    assert preview["max_date"] is None


@pytest.mark.django_db
def test_delete_by_filter_with_zero_matches_returns_zero_and_creates_no_audit(
    killer_brand_and_config, data_inserter_user
):
    """No matching rows means nothing is actually altered -- same as
    rollback_batch's "no audit for a no-op" behavior -- so this must not
    raise even for a user without Super Admin access."""
    brand, config = killer_brand_and_config

    deleted = delete_by_filter(brand, "menswear", "23-24", [4], data_inserter_user)

    assert deleted == 0
    assert DataAlterationAudit.objects.count() == 0


@pytest.mark.django_db
def test_data_inserter_is_blocked_from_delete_by_filter_and_it_is_audited(
    killer_brand_and_config, data_inserter_user
):
    brand, config = killer_brand_and_config
    _load(brand, config, data_inserter_user, KILLER_GOOD_ROWS)

    with pytest.raises(DataAlterationNotPermitted, match="requires Super Admin access"):
        delete_by_filter(brand, "menswear", "23-24", [4], data_inserter_user)

    assert FactSales.objects.filter(brand=brand).count() == 3  # untouched
    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is False
    assert audit.batch is None
    assert audit.action == DataAlterationAudit.Action.DELETE_FILTERED
    assert audit.details["product_line"] == "menswear"
    assert audit.details["financial_year"] == "23-24"
    assert audit.details["months"] == [4]
    assert audit.details["row_count"] == 3


@pytest.mark.django_db
def test_super_admin_can_delete_by_filter_and_it_is_audited(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    _load(brand, config, super_admin_user, KILLER_GOOD_ROWS)

    deleted = delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    assert deleted == 3
    audit = DataAlterationAudit.objects.get()
    assert audit.allowed is True
    assert audit.user == super_admin_user
    assert audit.action == DataAlterationAudit.Action.DELETE_FILTERED
    assert audit.batch is None


@pytest.mark.django_db
def test_delete_by_filter_refreshes_materialized_views_and_busts_cache(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    _load(brand, config, super_admin_user, KILLER_GOOD_ROWS)

    with (
        patch("apps.ingestion.loader.refresh_all") as mock_refresh,
        patch("apps.ingestion.loader.analytics_cache.bust") as mock_bust,
    ):
        delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    mock_refresh.assert_called_once()
    mock_bust.assert_called_once_with(brand.brand_id)


@pytest.mark.django_db
def test_delete_by_filter_with_zero_matches_does_not_refresh_or_bust_cache(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config

    with (
        patch("apps.ingestion.loader.refresh_all") as mock_refresh,
        patch("apps.ingestion.loader.analytics_cache.bust") as mock_bust,
    ):
        delete_by_filter(brand, "menswear", "23-24", [4], super_admin_user)

    mock_refresh.assert_not_called()
    mock_bust.assert_not_called()


@pytest.mark.django_db
def test_rollback_batch_now_refreshes_materialized_views_and_busts_cache(
    killer_brand_and_config, data_inserter_user, super_admin_user
):
    """Regression coverage for a gap found while building delete-by-filter:
    rollback_batch deleted fact rows but never refreshed the materialized
    views or busted the cache, unlike the load path -- dashboards would
    have kept showing rolled-back data until an unrelated refresh."""
    from apps.ingestion.loader import rollback_batch

    brand, config = killer_brand_and_config
    batch = _load(brand, config, data_inserter_user, KILLER_GOOD_ROWS)

    with (
        patch("apps.ingestion.loader.refresh_all") as mock_refresh,
        patch("apps.ingestion.loader.analytics_cache.bust") as mock_bust,
    ):
        rollback_batch(batch, super_admin_user)

    mock_refresh.assert_called_once()
    mock_bust.assert_called_once_with(brand.brand_id)


# --- Multi-month delete (client feedback: pick a brand + year, tick ------
# several months with data, delete all in one pass) -----------------------


@pytest.mark.django_db
def test_months_with_data_lists_every_month_that_has_rows(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    april_rows = [{**KILLER_GOOD_ROWS[0], "BILL NO \nINVOICE NO": 1}]
    # FY 23-24 runs April 2023 - March 2024, so "March of FY 23-24" is
    # calendar March 2024, not March 2023 (that's FY 22-23).
    march_rows = [
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2024, 3, 25), "BILL NO \nINVOICE NO": 2}
    ]
    _load(brand, config, super_admin_user, april_rows, "april.xlsx")
    _load(brand, config, super_admin_user, march_rows, "march.xlsx")

    months = months_with_data(brand, "menswear", "23-24")

    by_month = {m["date__month_no"]: m for m in months}
    assert set(by_month) == {3, 4}
    assert by_month[3]["row_count"] == 1
    assert by_month[3]["quantity"] == 1
    assert by_month[3]["date__month_name"] == "March"
    assert by_month[4]["row_count"] == 1


@pytest.mark.django_db
def test_months_with_data_is_empty_for_a_year_with_no_data(killer_brand_and_config):
    brand, config = killer_brand_and_config

    assert months_with_data(brand, "menswear", "23-24") == []


@pytest.mark.django_db
def test_delete_by_filter_removes_several_selected_months_leaves_others(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    april_rows = [{**KILLER_GOOD_ROWS[0], "BILL NO \nINVOICE NO": 1}]
    march_rows = [
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2024, 3, 25), "BILL NO \nINVOICE NO": 2}
    ]
    may_rows = [{**KILLER_GOOD_ROWS[0], "NEW DATE": date(2023, 5, 10), "BILL NO \nINVOICE NO": 3}]
    _load(brand, config, super_admin_user, april_rows, "april.xlsx")
    _load(brand, config, super_admin_user, march_rows, "march.xlsx")
    _load(brand, config, super_admin_user, may_rows, "may.xlsx")
    assert FactSales.objects.filter(brand=brand).count() == 3

    deleted = delete_by_filter(brand, "menswear", "23-24", [3, 4], super_admin_user)

    assert deleted == 2
    remaining = FactSales.objects.get(brand=brand)
    assert remaining.sale_date == date(2023, 5, 10)


@pytest.mark.django_db
def test_preview_delete_combines_totals_across_several_selected_months(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    april_rows = [{**KILLER_GOOD_ROWS[0], "BILL NO \nINVOICE NO": 1}]
    march_rows = [
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2024, 3, 25), "BILL NO \nINVOICE NO": 2}
    ]
    _load(brand, config, super_admin_user, april_rows, "april.xlsx")
    _load(brand, config, super_admin_user, march_rows, "march.xlsx")

    preview = preview_delete(brand, "menswear", "23-24", [3, 4])

    assert preview["row_count"] == 2
    assert preview["total_net_value"] == Decimal("4248.00")  # 2124.00 * 2
    assert preview["min_date"] == date(2023, 4, 5)
    assert preview["max_date"] == date(2024, 3, 25)


@pytest.mark.django_db
def test_multi_month_delete_is_audited_once_for_the_whole_selection(
    killer_brand_and_config, super_admin_user
):
    brand, config = killer_brand_and_config
    april_rows = [{**KILLER_GOOD_ROWS[0], "BILL NO \nINVOICE NO": 1}]
    march_rows = [
        {**KILLER_GOOD_ROWS[0], "NEW DATE": date(2024, 3, 25), "BILL NO \nINVOICE NO": 2}
    ]
    _load(brand, config, super_admin_user, april_rows, "april.xlsx")
    _load(brand, config, super_admin_user, march_rows, "march.xlsx")

    deleted = delete_by_filter(brand, "menswear", "23-24", [3, 4], super_admin_user)

    assert deleted == 2
    audit = DataAlterationAudit.objects.get()  # exactly one record, not one per month
    assert audit.details["months"] == [3, 4]
    assert audit.details["row_count"] == 2
