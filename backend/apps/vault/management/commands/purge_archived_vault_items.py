from django.conf import settings
from django.core.management.base import BaseCommand

from apps.vault.services import purge_expired_archives


class Command(BaseCommand):
    help = "Permanently delete vault items archived longer than the retention period (VAULT_ARCHIVE_RETENTION_DAYS)."

    def handle(self, *args, **options):
        deleted = purge_expired_archives()
        self.stdout.write(
            f"Purged {deleted} item(s) archived more than {settings.VAULT_ARCHIVE_RETENTION_DAYS} days ago."
        )
