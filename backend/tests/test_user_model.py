import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError

from apps.accounts.models import User
from apps.organizations.models import Organization


@pytest.fixture
def org():
    return Organization.objects.create(name="Acme", slug="acme")


@pytest.mark.django_db
def test_password_is_hashed_with_argon2(org):
    user = User.objects.create_user("alice@acme.test", org, "correct horse battery staple", full_name="Alice")
    assert user.password.startswith("argon2")
    assert "correct horse" not in user.password


@pytest.mark.django_db
def test_email_is_unique_case_insensitively(org):
    User.objects.create_user("alice@acme.test", org, None, full_name="Alice")
    other_org = Organization.objects.create(name="Other", slug="other")
    with pytest.raises(IntegrityError):
        User.objects.model(email="ALICE@acme.test", organization=other_org, full_name="Dup").save()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [User.Status.INVITED, User.Status.SUSPENDED, User.Status.DEACTIVATED])
def test_only_active_users_can_authenticate(org, status):
    password = "correct horse battery staple"
    User.objects.create_user("bob@acme.test", org, password, full_name="Bob", status=status)
    assert authenticate(username="bob@acme.test", password=password) is None


@pytest.mark.django_db
def test_active_user_can_authenticate(org):
    password = "correct horse battery staple"
    User.objects.create_user("carol@acme.test", org, password, full_name="Carol", status=User.Status.ACTIVE)
    assert authenticate(username="carol@acme.test", password=password) is not None
    assert authenticate(username="  CAROL@Acme.test ", password=password) is not None


@pytest.mark.django_db
def test_user_requires_organization():
    with pytest.raises(ValueError):
        User.objects.create_user("dave@acme.test", None, "x", full_name="Dave")
