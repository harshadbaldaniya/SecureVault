"""Vault key rotation. See apps/vault/rotation.py and docs/security-model.md for the full procedure.

    manage.py rotate_vault_keys --rewrap-keks            # after adding a KEK version to SV_VAULT_KEK_KEYS
    manage.py rotate_vault_keys --rotate-deks [--org X]  # replace data keys and re-encrypt records
    manage.py rotate_vault_keys --reindex                # after adding a version to SV_BLIND_INDEX_KEYS
"""

from django.core.management.base import BaseCommand, CommandError

from apps.organizations.models import Organization
from apps.vault import rotation


class Command(BaseCommand):
    help = "Rotate vault encryption keys."

    def add_arguments(self, parser):
        parser.add_argument("--rewrap-keks", action="store_true", help="Re-wrap data keys under the newest KEK.")
        parser.add_argument("--rotate-deks", action="store_true", help="Rotate data keys and re-encrypt records.")
        parser.add_argument("--reindex", action="store_true", help="Recompute blind indexes under the newest key.")
        parser.add_argument("--org", help="Limit --rotate-deks to one organization slug.")

    def handle(self, *args, rewrap_keks, rotate_deks, reindex, org, **options):
        if not (rewrap_keks or rotate_deks or reindex):
            raise CommandError("Choose at least one of --rewrap-keks, --rotate-deks, --reindex.")

        if rewrap_keks:
            self.stdout.write(f"Re-wrapped {rotation.rewrap_data_keys()} data key(s).")
        if rotate_deks:
            organizations = Organization.objects.filter(slug=org) if org else Organization.objects.all()
            if org and not organizations.exists():
                raise CommandError(f"No organization with slug '{org}'.")
            for organization in organizations:
                moved = rotation.rotate_data_key(organization)
                self.stdout.write(f"{organization.slug}: re-encrypted {moved} record(s) under a new data key.")
        if reindex:
            self.stdout.write(f"Re-indexed {rotation.reindex_blind_indexes()} credential(s).")


