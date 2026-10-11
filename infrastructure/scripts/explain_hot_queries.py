"""Seeds a SCRATCH database with realistic volume and prints the PostgreSQL plan of the application's hottest queries.

It exists to back the claim "indexes are based on actual query patterns" with evidence. Never run it against a database
you care about: audit records are append-only, so the data it creates cannot be removed again (drop the scratch
database instead).

    # 1. a scratch database next to the development one, migrated by Django
    docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" sv_explain'
    POSTGRES_DB=sv_explain python manage.py migrate          # from backend/, with the venv active
    # 2. seed + explain (AUDIT_ROWS defaults to 100000)
    POSTGRES_DB=sv_explain python manage.py shell < ../infrastructure/scripts/explain_hot_queries.py
    # 3. clean up
    docker compose exec db sh -c 'dropdb -U "$POSTGRES_USER" sv_explain'

Plans on a small dataset are not representative (PostgreSQL rightly prefers sequential scans on tiny tables), which is why
this seeds volume first and runs ANALYZE.
"""

import os
import re
import uuid
from datetime import timedelta

from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.organizations.models import Organization
from apps.sharing.models import Share
from apps.vault.models import Credential

AUDIT_ROWS = int(os.environ.get("AUDIT_ROWS", "100000"))
USERS, CREDENTIALS_PER_USER, SHARES_PER_USER = 200, 20, 20

assert connection.settings_dict["NAME"].startswith("sv_explain"), "refusing to seed anything but a scratch database"

now = timezone.now()
org, _ = Organization.objects.get_or_create(slug="explain", defaults={"name": "Explain"})
if not User.objects.filter(organization=org).exists():
    users = User.objects.bulk_create(
        [
            User(email=f"u{i:04d}@explain.test", organization=org, full_name=f"User {i}", status="ACTIVE", password="!")
            for i in range(USERS)
        ]
    )
    credentials = Credential.objects.bulk_create(
        [
            Credential(
                organization=org, owner=u, title=f"Cred {n}", secret_ciphertext="v1:x:y", key_version=1,
                password_changed_at=now, blind_index=uuid.uuid4().hex, blind_index_version=1, entropy_bits=80,
            )
            for u in users for n in range(CREDENTIALS_PER_USER)
        ],
        batch_size=2000,
    )
    shares = []
    for index, u in enumerate(users):
        for n in range(SHARES_PER_USER):
            owner_credential = credentials[((index + 1 + n) % USERS) * CREDENTIALS_PER_USER + n % CREDENTIALS_PER_USER]
            if owner_credential.owner_id == u.pk:
                continue
            shares.append(
                Share(organization=org, credential=owner_credential, grantor=owner_credential.owner, grantee=u,
                      permission="VIEW", depth=0, expires_at=now + timedelta(days=20))
            )
    Share.objects.bulk_create(shares, batch_size=2000, ignore_conflicts=True)

    actions = ["LOGIN", "REVEAL", "COPY", "CREATE", "EDIT", "SHARE", "REVOKE", "LOGOUT"]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH people AS (SELECT array_agg(id ORDER BY id) AS ids FROM accounts_user WHERE organization_id = %s)
            INSERT INTO audit_auditlog (chain_key, sequence, prev_hash, hash, created_at, organization_id, actor_id,
                actor_email, action, outcome, target_type, target_id, target_label, reason, metadata, user_agent, request_id)
            SELECT 'org:' || %s, g, md5((g - 1)::text), md5(g::text) || md5((g * 7)::text),
                   now() - (g * interval '20 seconds'), %s,
                   people.ids[1 + g %% %s], 'u@explain.test', (%s::text[])[1 + g %% %s], 'SUCCESS', 'credential',
                   g::text, 'Cred ' || g, '', '{}'::jsonb, '', ''
            FROM generate_series(1, %s) AS g, people
            """,
            [str(org.pk), str(org.pk), str(org.pk), USERS, actions, len(actions), AUDIT_ROWS],
        )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE")

user = User.objects.filter(organization=org).order_by("email").first()
credential = Credential.objects.filter(organization=org).first()
since = now - timedelta(days=7)

shared_with_user = Share.objects.filter(grantee=user, revoked_at__isnull=True, expires_at__gt=now)
cases = {
    "Audit log, newest first (org filter, page 1)": AuditLog.objects.filter(organization=org).order_by("-created_at", "-id")[:25],
    "Audit log filtered by action and date": AuditLog.objects.filter(
        organization=org, action="REVEAL", created_at__gte=since
    ).order_by("-created_at", "-id")[:25],
    "Anomaly rule: one user's reveals in the last 10 minutes": AuditLog.objects.filter(
        organization=org, actor_id=user.pk, action="REVEAL", created_at__gte=now - timedelta(minutes=10)
    ),
    "Dashboard: reveals and copies per user over 7 days": AuditLog.objects.filter(
        organization=org, actor_id=user.pk, action__in=["REVEAL", "COPY"], outcome="SUCCESS", created_at__gte=since
    ),
    "Access check: grants of one user on one credential": Share.objects.filter(
        credential_id=credential.pk, grantee_id=user.pk, revoked_at__isnull=True
    ),
    "Shared with me: grants received by a user": shared_with_user,
    "Credential list for a user (owned or shared)": Credential.objects.filter(organization=org).filter(
        Q(owner=user) | (Q(pk__in=shared_with_user.values("credential_id")) & Q(archived_at__isnull=True))
    ).order_by("title")[:25],
    "Delegation tree of one credential": Share.objects.filter(credential_id=credential.pk),
    "Expiry sweep: grants expiring soon": Share.objects.filter(
        organization=org, revoked_at__isnull=True, burned_at__isnull=True, expires_at__lte=now + timedelta(hours=24)
    ),
}

counts = {
    "audit records": AuditLog.objects.count(),
    "credentials": Credential.objects.count(),
    "shares": Share.objects.count(),
    "users": User.objects.count(),
}
print("Dataset:", counts)
print()
print("| Query | Plan (top scan) | Execution time |")
print("|---|---|---|")
for name, queryset in cases.items():
    plan = queryset.explain(analyze=True)
    scans = re.findall(r"(Seq Scan on \w+|Index (?:Only )?Scan(?: Backward)? using \w+ on \w+|Bitmap Index Scan on \w+)", plan)
    timing = re.search(r"Execution Time: ([\d.]+) ms", plan)
    print(f"| {name} | {'; '.join(dict.fromkeys(scans)) or 'n/a'} | {timing.group(1) if timing else '?'} ms |")
