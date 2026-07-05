import pytest

from apps.masterdata.models import DimBrand


@pytest.mark.django_db
def test_super_admin_has_full_masterdata_permissions(super_admin_user):
    assert super_admin_user.has_perm("masterdata.add_dimbrand")
    assert super_admin_user.has_perm("masterdata.change_dimbrand")
    assert super_admin_user.has_perm("masterdata.delete_dimbrand")
    assert super_admin_user.has_perm("masterdata.view_dimbrand")


@pytest.mark.django_db
def test_data_inserter_has_view_only_masterdata_permissions(data_inserter_user):
    assert data_inserter_user.has_perm("masterdata.view_dimbrand")
    assert not data_inserter_user.has_perm("masterdata.add_dimbrand")
    assert not data_inserter_user.has_perm("masterdata.change_dimbrand")
    assert not data_inserter_user.has_perm("masterdata.delete_dimbrand")


@pytest.mark.django_db
def test_seed_roles_is_idempotent_and_tracks_new_permissions(seed_roles):
    from django.contrib.auth.models import Group, Permission
    from django.core.management import call_command

    super_admin = Group.objects.get(name="Super Admin")
    assert super_admin.permissions.count() == Permission.objects.count()

    # Re-running after new permissions appear (e.g. a future model) should
    # pick them up automatically -- Super Admin always means "everything".
    call_command("seed_roles")
    assert super_admin.permissions.count() == Permission.objects.count()


@pytest.mark.django_db
def test_data_inserter_cannot_log_into_django_admin(client, data_inserter_user):
    client.login(email="inserter@example.com", password="StrongPass123")

    response = client.get("/admin/")

    assert response.status_code == 302
    assert "/admin/login/" in response.url


@pytest.mark.django_db
def test_super_admin_can_log_into_django_admin(client, super_admin_user):
    client.force_login(super_admin_user)

    response = client.get("/admin/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_super_admin_sees_masterdata_models_in_admin(client, super_admin_user):
    DimBrand.objects.create(brand_code="KILLER", brand_name="Killer")
    client.force_login(super_admin_user)

    response = client.get("/admin/masterdata/dimbrand/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_data_inserter_blocked_from_masterdata_admin_changelist(client, data_inserter_user):
    client.login(email="inserter@example.com", password="StrongPass123")

    response = client.get("/admin/masterdata/dimbrand/")

    assert response.status_code == 302
