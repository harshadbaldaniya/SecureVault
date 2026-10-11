from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

from core.models import TimeStampedModel


class UserManager(BaseUserManager):
    def get_by_natural_key(self, username):
        return self.get(email__iexact=username.strip())

    def create_user(self, email: str, organization, password: str | None = None, **extra):
        if not email:
            raise ValueError("Email is required.")
        if organization is None:
            raise ValueError("Every user must belong to an organization.")
        user = self.model(email=self.normalize_email(email).lower(), organization=organization, **extra)
        # None -> unusable password (e.g. invited users who have not activated yet).
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, TimeStampedModel):
    """Employee identity.

    Deliberately does not use Django's PermissionsMixin / superuser flag: authorization
    is SecureVault's own role + resource model, always scoped to `organization`.
    Emails are globally unique (case-insensitive) so login needs no organization selector.
    """

    class Role(models.TextChoices):
        ORG_ADMIN = "ORG_ADMIN", "Organization Administrator"
        SEC_ADMIN = "SEC_ADMIN", "Security Administrator"
        EMPLOYEE = "EMPLOYEE", "Employee"

    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DEACTIVATED = "DEACTIVATED", "Deactivated"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="users"
    )
    email = models.EmailField(max_length=254, unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INVITED)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        # Django's ModelBackend and login() honour this; only ACTIVE users may authenticate.
        return self.status == self.Status.ACTIVE

    @property
    def is_admin(self) -> bool:
        return self.role in {self.Role.ORG_ADMIN, self.Role.SEC_ADMIN}
