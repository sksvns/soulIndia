from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_brand_list_returns_active_brands_sorted_by_name(data_inserter_user):
    call_command("seed_brands", stdout=StringIO())
    client = _authed_client(data_inserter_user)

    response = client.get("/api/masterdata/brands/")

    assert response.status_code == 200
    codes = [b["brand_code"] for b in response.data["brands"]]
    names = [b["brand_name"] for b in response.data["brands"]]
    assert set(codes) == {"KILLER", "PEPE", "JUNIOR_KILLER", "KRAUS"}
    assert names == sorted(names)


@pytest.mark.django_db
def test_brand_list_excludes_inactive_brands(data_inserter_user):
    from apps.masterdata.models import DimBrand

    call_command("seed_brands", stdout=StringIO())
    DimBrand.objects.filter(brand_code="PEPE").update(active=False)
    client = _authed_client(data_inserter_user)

    response = client.get("/api/masterdata/brands/")

    codes = [b["brand_code"] for b in response.data["brands"]]
    assert "PEPE" not in codes
    assert "KILLER" in codes


@pytest.mark.django_db
def test_unauthenticated_cannot_list_brands():
    client = APIClient()

    response = client.get("/api/masterdata/brands/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_upload_config_list_returns_brand_product_line_pairs(data_inserter_user):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    client = _authed_client(data_inserter_user)

    response = client.get("/api/masterdata/upload-configs/")

    assert response.status_code == 200
    pairs = {(c["brand_code"], c["product_line"]) for c in response.data["upload_configs"]}
    assert pairs == {
        ("KILLER", "menswear"),
        ("PEPE", "menswear"),
        ("JUNIOR_KILLER", "kids"),
        ("KRAUS", "womenswear"),
    }


@pytest.mark.django_db
def test_upload_config_list_excludes_inactive_configs(data_inserter_user):
    from apps.masterdata.models import BrandUploadConfig

    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    BrandUploadConfig.objects.filter(brand__brand_code="PEPE").update(active=False)
    client = _authed_client(data_inserter_user)

    response = client.get("/api/masterdata/upload-configs/")

    pairs = {(c["brand_code"], c["product_line"]) for c in response.data["upload_configs"]}
    assert ("PEPE", "menswear") not in pairs


@pytest.mark.django_db
def test_unauthenticated_cannot_list_upload_configs():
    client = APIClient()

    response = client.get("/api/masterdata/upload-configs/")

    assert response.status_code == 401
