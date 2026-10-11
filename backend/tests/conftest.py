import itertools

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organizations.models import Organization

PASSWORD = "Sturdy-Test-Passphrase-42"
_counter = itertools.count()


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    """Tests use an in-memory cache so lockout/throttle counters never leak between tests or into dev Redis."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme", slug="acme")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Globex", slug="globex")


@pytest.fixture
def make_user(db, org):
    def _make(role=User.Role.EMPLOYEE, status=User.Status.ACTIVE, organization=None, **extra):
        n = next(_counter)
        return User.objects.create_user(
            extra.pop("email", f"user{n}@example.test"),
            organization or org,
            PASSWORD,
            full_name=extra.pop("full_name", f"User {n}"),
            role=role,
            status=status,
            **extra,
        )

    return _make


@pytest.fixture
def admin(make_user):
    return make_user(role=User.Role.ORG_ADMIN, full_name="Olivia Admin")


@pytest.fixture
def sec_admin(make_user):
    return make_user(role=User.Role.SEC_ADMIN, full_name="Sam Security")


@pytest.fixture
def employee(make_user):
    return make_user(full_name="Eve Employee")


@pytest.fixture
def other_admin(make_user, other_org):
    return make_user(role=User.Role.ORG_ADMIN, organization=other_org, full_name="Gary Globex")


@pytest.fixture
def client_for():
    """APIClient logged in as `user` through Django's real login() (signals fire)."""

    def _client(user):
        client = APIClient()
        client.force_login(user)
        return client

    return _client


@pytest.fixture
def anon():
    return APIClient()
