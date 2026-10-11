import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

ARGS = ["--org-name", "Acme Ltd", "--org-slug", "acme-ltd", "--email", "Boss@Acme.test", "--full-name", "Boss"]


def test_bootstrap_creates_org_and_active_admin(monkeypatch):
    monkeypatch.setenv("SV_BOOTSTRAP_PASSWORD", "Bootstrap-Passphrase-31")
    call_command("bootstrap_org", *ARGS)
    admin = User.objects.get(email="boss@acme.test")
    assert admin.role == User.Role.ORG_ADMIN
    assert admin.status == User.Status.ACTIVE
    assert admin.organization.slug == "acme-ltd"
    assert admin.check_password("Bootstrap-Passphrase-31")


def test_bootstrap_rejects_weak_password(monkeypatch):
    monkeypatch.setenv("SV_BOOTSTRAP_PASSWORD", "password")
    with pytest.raises(CommandError, match="Password rejected"):
        call_command("bootstrap_org", *ARGS)
    assert not User.objects.exists()


def test_bootstrap_refuses_existing_slug(monkeypatch, org):
    monkeypatch.setenv("SV_BOOTSTRAP_PASSWORD", "Bootstrap-Passphrase-31")
    with pytest.raises(CommandError, match="already exists"):
        call_command(
            "bootstrap_org", "--org-name", "X", "--org-slug", org.slug, "--email", "x@x.test", "--full-name", "X"
        )
