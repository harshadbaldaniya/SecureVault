from django.core.management.base import BaseCommand

from apps.sharing.services import process_expiry


class Command(BaseCommand):
    help = "Notify grantees about grants that expire within 24 hours or have expired (run every few minutes)."

    def handle(self, *args, **options):
        counts = process_expiry()
        self.stdout.write(f"Expiring-soon notices: {counts['expiring']}; expired notices: {counts['expired']}.")
