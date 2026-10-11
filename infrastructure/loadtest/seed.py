"""Seeds a throw-away organization for load tests and prints, as JSON, one pre-authenticated session per user.

TEST STACKS ONLY (the sv-smoke project or any stack you will delete afterwards): audit records are append-only,
so the organization this creates cannot be cleaned out of a database you want to keep.

Run it inside the backend container, with the number of employees and credentials per employee as arguments:

    docker compose -p sv-smoke --env-file .env.smoke -f docker-compose.prod.yml exec -T \
        -e LOAD_USERS=20 -e LOAD_CREDENTIALS=10 backend python manage.py shell < infrastructure/loadtest/seed.py \
        > loadtest-seed.json

Sessions are created with Django's test client `force_login`, so no sign-in throttle is involved and no password is
ever needed. The JSON contains live session keys: keep it out of the repository (it is git-ignored by name) and delete
it with the stack.
"""

import json
import os
import secrets

from django.test import Client

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.vault import services as vault
from apps.vault.models import Credential

USERS = int(os.environ.get("LOAD_USERS", "20"))
CREDENTIALS = int(os.environ.get("LOAD_CREDENTIALS", "10"))

org, _ = Organization.objects.get_or_create(slug="loadtest", defaults={"name": "Load Test Org"})


def session_for(user):
    client = Client()
    client.force_login(user)
    return client.cookies["sv_session"].value


def person(email, name, role):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(
            email, org, secrets.token_urlsafe(24), full_name=name, role=role, status=User.Status.ACTIVE
        )
    return user


admin = person("admin@load.test", "Load Admin", User.Role.ORG_ADMIN)
people = []
for index in range(USERS):
    user = person(f"user{index:03d}@load.test", f"Load User {index:03d}", User.Role.EMPLOYEE)
    ids = [str(pk) for pk in Credential.objects.filter(owner=user, archived_at__isnull=True).values_list("pk", flat=True)]
    for number in range(len(ids), CREDENTIALS):
        credential = vault.create_credential(
            user=user,
            title=f"Service {number:02d}",
            username=f"svc{number:02d}",
            password=f"Ld!9{secrets.token_urlsafe(18)}Z",  # always meets the default policy
        )
        ids.append(str(credential.pk))
    people.append({"email": user.email, "session": session_for(user), "credentials": ids})

print(json.dumps({"admin": {"email": admin.email, "session": session_for(admin)}, "users": people}))
