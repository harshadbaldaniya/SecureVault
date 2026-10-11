import os

from apps.accounts.models import User
from apps.organizations.models import Organization

org, _ = Organization.objects.get_or_create(slug="latency-test", defaults={"name": "Latency Test"})
for email, role in [("sec@latency.test", "SEC_ADMIN"), ("emp@latency.test", "EMPLOYEE")]:
    user = User.objects.filter(email=email).first() or User.objects.create_user(
        email, org, None, full_name=email.split("@")[0], role=role, status="ACTIVE"
    )
    user.set_password(os.environ["PW"])
    user.save()
print("latency org ready")
