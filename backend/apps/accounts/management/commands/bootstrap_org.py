"""Create an organization and its first Organization Administrator.

There is no default admin account. The password is typed at a prompt, or, for
non-interactive setups, read from the environment variable SV_BOOTSTRAP_PASSWORD.

    python manage.py bootstrap_org --org-name "Acme Ltd" --org-slug acme \
        --email admin@acme.test --full-name "Acme Admin"
"""

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.organizations.models import Organization

PASSWORD_ENV = "SV_BOOTSTRAP_PASSWORD"  # noqa: S105 - name of an env var, not a password


class Command(BaseCommand):
    help = "Create an organization and its first Organization Administrator."

    def add_arguments(self, parser):
        parser.add_argument("--org-name", required=True)
        parser.add_argument("--org-slug", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--full-name", required=True)

    def handle(self, *args, org_name, org_slug, email, full_name, **options):
        if Organization.objects.filter(slug=org_slug).exists():
            raise CommandError(f"Organization '{org_slug}' already exists.")
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("A user with this email already exists.")

        password = self._read_password()
        candidate = User(email=email.lower(), full_name=full_name)
        try:
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError("Password rejected: " + " ".join(exc.messages)) from None

        with transaction.atomic():
            org = Organization.objects.create(name=org_name, slug=org_slug)
            User.objects.create_user(
                email, org, password, full_name=full_name, role=User.Role.ORG_ADMIN, status=User.Status.ACTIVE
            )
        self.stdout.write(self.style.SUCCESS(f"Created organization '{org_slug}' with administrator {email.lower()}."))

    @staticmethod
    def _read_password() -> str:
        from_env = os.environ.get(PASSWORD_ENV)
        if from_env:
            return from_env
        first = getpass.getpass("Administrator password: ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            raise CommandError("Passwords do not match.")
        return first
