from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditChainHead
from apps.audit.services import verify_chain


class Command(BaseCommand):
    help = "Recompute audit hash chains and report the first broken record in each."

    def add_arguments(self, parser):
        parser.add_argument("--chain", help="Verify one chain (e.g. 'global' or 'org:<uuid>'). Default: all chains.")

    def handle(self, *args, chain=None, **options):
        all_chains = AuditChainHead.objects.order_by("chain_key").values_list("chain_key", flat=True)
        keys = [chain] if chain else list(all_chains)
        broken = 0
        for key in keys:
            result = verify_chain(key)
            if result["valid"]:
                self.stdout.write(self.style.SUCCESS(f"{key}: OK ({result['checked']} records)"))
            else:
                broken += 1
                self.stdout.write(self.style.ERROR(f"{key}: BROKEN at sequence {result['broken_at_sequence']}"))
        if broken:
            raise CommandError(f"{broken} chain(s) failed verification.")
