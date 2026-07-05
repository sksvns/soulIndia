from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_redis_cache():
    # Unlike Postgres (reset per-test by pytest-django's transaction
    # rollback), Redis is a real shared external service -- cache entries
    # from one test are otherwise visible to the next.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def seed_roles(db):
    call_command("seed_roles", stdout=StringIO())


@pytest.fixture
def seed_calendar(db):
    call_command("seed_calendar", "--start=2020-04-01", "--end=2031-03-31", stdout=StringIO())


@pytest.fixture
def super_admin_user(seed_roles):
    user = User.objects.create_user(
        email="admin@example.com", password="StrongPass123", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Super Admin"))
    return user


@pytest.fixture
def data_inserter_user(seed_roles):
    user = User.objects.create_user(
        email="inserter@example.com", password="StrongPass123", is_staff=False
    )
    user.groups.add(Group.objects.get(name="Data Inserter"))
    return user
