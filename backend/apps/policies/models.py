from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel


class SecurityPolicy(TimeStampedModel):
    """The organization's single active security policy.

    Credential rules (min length, character classes, max age) apply to secrets stored
    in the vault (Phase 2). Employee login passwords follow Django's validators.
    Enforcement of each flag lands with its module: view-once (Phase 3),
    device trust and MFA (Phase 1.4 / Phase 4).
    """

    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.PROTECT, related_name="security_policy"
    )
    name = models.CharField(max_length=120, default="Default security policy")

    # Vault credential rules
    min_password_length = models.PositiveSmallIntegerField(
        default=14, validators=[MinValueValidator(8), MaxValueValidator(128)]
    )
    require_uppercase = models.BooleanField(default=True)
    require_numbers = models.BooleanField(default=True)
    require_symbols = models.BooleanField(default=True)
    max_password_age_days = models.PositiveSmallIntegerField(
        default=90, validators=[MaxValueValidator(3650)], help_text="0 means credentials never expire."
    )
    expiry_warning_days = models.PositiveSmallIntegerField(default=14, validators=[MaxValueValidator(365)])

    # Sharing and access
    allow_view_once = models.BooleanField(default=True)
    max_share_duration_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(365)]
    )

    # Zero-trust
    require_device_trust = models.BooleanField(default=False)
    require_mfa = models.BooleanField(default=False)
    # When on, an open HIGH-severity anomaly alert pauses that user's sensitive actions until reviewed.
    block_on_high_risk = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.name} ({self.organization_id})"


def policy_for(organization) -> SecurityPolicy:
    policy, _ = SecurityPolicy.objects.get_or_create(organization=organization)
    return policy
