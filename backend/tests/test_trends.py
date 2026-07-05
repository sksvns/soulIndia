from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.analytics import queries
from apps.analytics.materialized_views import refresh_all
from apps.ingestion.loader import load_batch
from apps.ingestion.pipeline import run_pipeline
from apps.masterdata.models import BrandUploadConfig, DimBrand
from tests.ingestion_fixtures import KILLER_TREND_ROWS, killer_workbook

# Hand-computed from KILLER_TREND_ROWS (tests/ingestion_fixtures.py):
#   ESIS170 row1: 2023-04-05 SHIRTS SS23  mrp=1000 net=1000 disc=0   qty=1
#   ESIS170 row2: 2023-07-10 SHIRTS SS23  mrp=2000 net=1800 disc=200 qty=1
#   ESIS170 row3: 2023-10-15 JEANS  AW23  mrp=750x2=1500 net=1500 disc=0 qty=2
#   ESIS170 row4: 2024-04-20 SHIRTS SS24  mrp=3000 net=3000 disc=0   qty=1
#   ESIS999 row5: 2023-04-05 SHIRTS SS23  mrp=500  net=500  disc=0   qty=1
#
# FY 23-24 (rows 1-3, ESIS170 only): net=1000+1800+1500=4300, mrp=4500, qty=4
# FY 24-25 (row 4): net=3000, mrp=3000, qty=1


@pytest.fixture
def killer_brand_and_config(seed_calendar):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    return brand, config


@pytest.fixture
def loaded_trend_data(killer_brand_and_config, data_inserter_user):
    from apps.ingestion.models import UploadBatch

    brand, config = killer_brand_and_config
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="trend.xlsx",
        object_key="uploads/killer/menswear/trend.xlsx",
    )
    result = run_pipeline(brand, config, killer_workbook(KILLER_TREND_ROWS), "trend.xlsx")
    assert result.ok, result.errors
    load_batch(batch, result.rows)
    refresh_all()
    return brand


@pytest.mark.django_db
def test_store_trend_yoy_groups_by_financial_year(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.store_trend(brand.brand_id, "financial_year", "net", "ESIS170")

    by_label = {row["label"]: row["value"] for row in result}
    assert by_label == {"23-24": Decimal("4300.00"), "24-25": Decimal("3000.00")}
    # lexicographic order happens to be chronological order for "YY-YY" text
    assert [row["label"] for row in result] == ["23-24", "24-25"]


@pytest.mark.django_db
def test_store_trend_yoy_metric_selection_mrp_vs_qty(loaded_trend_data):
    brand = loaded_trend_data

    mrp_result = queries.store_trend(brand.brand_id, "financial_year", "mrp", "ESIS170")
    qty_result = queries.store_trend(brand.brand_id, "financial_year", "quantity", "ESIS170")
    by_mrp = {r["label"]: r["value"] for r in mrp_result}
    by_qty = {r["label"]: r["value"] for r in qty_result}

    assert by_mrp == {"23-24": Decimal("4500.00"), "24-25": Decimal("3000.00")}
    assert by_qty == {"23-24": 4, "24-25": 1}


@pytest.mark.django_db
def test_store_trend_mom_orders_chronologically_across_financial_year_boundary(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.store_trend(brand.brand_id, "month", "net", "ESIS170")

    # Naive text/month_no sort would put "April" (both 2023 and 2024) before
    # "July"/"October" 2023 or would collapse the two Aprils together --
    # calendar_year-first ordering is what proves the MoM axis is real.
    assert [row["label"] for row in result] == [
        "April 2023",
        "July 2023",
        "October 2023",
        "April 2024",
    ]
    values = [row["value"] for row in result]
    assert values == [
        Decimal("1000.00"),
        Decimal("1800.00"),
        Decimal("1500.00"),
        Decimal("3000.00"),
    ]


@pytest.mark.django_db
def test_store_trend_season_by_season_orders_by_earliest_occurrence(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.store_trend(brand.brand_id, "season", "net", "ESIS170")

    # SS23 (Apr+Jul 2023) -> AW23 (Oct 2023) -> SS24 (Apr 2024): season text
    # alone (SS23 < SS24 < AW23 lexically) would get this order wrong.
    assert [row["label"] for row in result] == ["SS23", "AW23", "SS24"]
    by_label = {row["label"]: row["value"] for row in result}
    assert by_label["SS23"] == Decimal("2800.00")  # 1000 + 1800
    assert by_label["AW23"] == Decimal("1500.00")
    assert by_label["SS24"] == Decimal("3000.00")


@pytest.mark.django_db
def test_store_trend_scoped_to_one_store_excludes_other_stores(loaded_trend_data):
    brand = loaded_trend_data

    scoped = queries.store_trend(brand.brand_id, "financial_year", "net", "ESIS999")
    unscoped = queries.store_trend(brand.brand_id, "financial_year", "net", None)

    assert {row["label"]: row["value"] for row in scoped} == {"23-24": Decimal("500.00")}
    # unscoped (whole brand) FY 23-24 includes ESIS170's 4300 + ESIS999's 500
    assert {row["label"]: row["value"] for row in unscoped}["23-24"] == Decimal("4800.00")


@pytest.mark.django_db
def test_category_trend_filters_by_category_across_time(loaded_trend_data):
    brand = loaded_trend_data

    shirts = queries.category_trend(brand.brand_id, "financial_year", "net", category="SHIRTS")
    jeans = queries.category_trend(brand.brand_id, "financial_year", "net", category="JEANS")

    # SHIRTS: FY23-24 = row1(1000)+row2(1800)+ESIS999 row5(500) = 3300; FY24-25 = row4(3000)
    assert {r["label"]: r["value"] for r in shirts} == {
        "23-24": Decimal("3300.00"),
        "24-25": Decimal("3000.00"),
    }
    # JEANS: only row3, FY23-24 = 1500
    assert {r["label"]: r["value"] for r in jeans} == {"23-24": Decimal("1500.00")}


@pytest.mark.django_db
def test_category_trend_scoped_to_store_and_category_combined(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.category_trend(
        brand.brand_id, "financial_year", "net", category="SHIRTS", store_codes=["ESIS170"]
    )

    # Excludes ESIS999's 500 -- only ESIS170's SHIRTS rows (1000 + 1800)
    assert {r["label"]: r["value"] for r in result} == {
        "23-24": Decimal("3300.00") - Decimal("500.00"),
        "24-25": Decimal("3000.00"),
    }


@pytest.mark.django_db
def test_trend_with_unknown_dimension_raises_value_error(loaded_trend_data):
    brand = loaded_trend_data

    with pytest.raises(ValueError):
        queries.store_trend(brand.brand_id, "not_a_real_dimension", "net", "ESIS170")


@pytest.mark.django_db
def test_trend_for_store_with_no_data_returns_empty_list(loaded_trend_data):
    brand = loaded_trend_data

    result = queries.store_trend(brand.brand_id, "financial_year", "net", "NOSUCHSTORE")

    assert result == []
