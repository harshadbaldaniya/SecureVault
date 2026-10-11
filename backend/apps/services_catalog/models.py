from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models
from django.db.models.functions import Lower

from core.models import TimeStampedModel

# Only web URLs; rejects javascript:, data:, ftp:, file: and similar schemes.
web_url = URLValidator(schemes=["http", "https"])


class ServiceCatalog(TimeStampedModel):
    """A third-party SaaS tool or internal service that credentials belong to.

    SecureVault never fetches base_url/icon_url server-side (no SSRF surface);
    they are only displayed as links/images in the UI.
    """

    class Category(models.TextChoices):
        CLOUD = "CLOUD", "Cloud infrastructure"
        DATABASE = "DATABASE", "Database"
        DEVOPS = "DEVOPS", "DevOps / CI"
        SAAS = "SAAS", "SaaS application"
        INTERNAL = "INTERNAL", "Internal service"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="services")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.OTHER)
    base_url = models.CharField(max_length=500, blank=True, validators=[web_url])
    icon_url = models.CharField(max_length=500, blank=True, validators=[web_url])
    default_port = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(65535)]
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint("organization", Lower("name"), name="services_org_name_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.name
