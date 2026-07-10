from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User


@pytest.mark.django_db
def test_create_super_admin_creates_user_in_super_admin_group():
    call_command(
        "create_super_admin",
        "--email=admin@example.com",
        "--password=StrongPassword123",
        stdout=StringIO(),
    )

    user = User.objects.get(email="admin@example.com")
    assert user.is_staff is True
    assert user.groups.filter(name="Super Admin").exists()
    assert user.has_perm("ingestion.add_uploadbatch")
    assert user.check_password("StrongPassword123")


@pytest.mark.django_db
def test_create_super_admin_is_idempotent_and_updates_password():
    call_command(
        "create_super_admin",
        "--email=admin@example.com",
        "--password=FirstPassword123",
        stdout=StringIO(),
    )
    call_command(
        "create_super_admin",
        "--email=admin@example.com",
        "--password=SecondPassword456",
        stdout=StringIO(),
    )

    assert User.objects.filter(email="admin@example.com").count() == 1
    user = User.objects.get(email="admin@example.com")
    assert user.check_password("SecondPassword456")


@pytest.mark.django_db
def test_create_super_admin_rejects_short_password():
    with pytest.raises(CommandError, match="at least 12 characters"):
        call_command(
            "create_super_admin",
            "--email=admin@example.com",
            "--password=short",
            stdout=StringIO(),
        )
