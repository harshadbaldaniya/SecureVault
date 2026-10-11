from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

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

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="users")
    email = models.EmailField(max_length=254, unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INVITED)
    department = models.ForeignKey(
        "departments.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="users"
    )

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


class UserSession(models.Model):
    """Maps server-side session keys to users so sessions can be revoked per user/org.

    Revocation deletes the django_session row itself; this table only makes the
    sessions findable (Django's session table cannot be queried by user).
    """

    session_key = models.CharField(max_length=40, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    # Linked when the browser identifies its device, so suspending/revoking a device signs it out.
    device = models.ForeignKey(
        "devices.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self) -> str:
        # Never render the session key itself: it is a bearer credential.
        return f"Session of {self.user_id} since {self.created_at:%Y-%m-%d %H:%M}"


class TOTPDevice(models.Model):
    """A user's authenticator app. The shared secret is stored AES-256-GCM encrypted."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp_device")
    secret_encrypted = models.CharField(max_length=200)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # Highest 30-second time step accepted so far; older or equal steps are replays.
    last_used_step = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"TOTP for {self.user_id} ({'confirmed' if self.confirmed_at else 'pending'})"


class RecoveryCode(models.Model):
    """Single-use MFA fallback code; only its SHA-256 hash is stored (codes carry 80 bits of entropy)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "code_hash"], name="recovery_code_unique")]

    def __str__(self) -> str:
        return f"Recovery code for {self.user_id}"


class PasswordResetToken(TimeStampedModel):
    """Single-use, short-lived password reset token; only its SHA-256 hash is stored."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Password reset for {self.user_id}"

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class Invitation(TimeStampedModel):
    """Single-use, expiring activation link for an INVITED user.

    Only the SHA-256 hash of the token is stored; the raw token is shown once.
    """

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="invitations")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="invitations")
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="sent_invitations")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "created_at"])]

    @property
    def state(self) -> str:
        if self.accepted_at:
            return "ACCEPTED"
        if self.revoked_at:
            return "REVOKED"
        if self.expires_at <= timezone.now():
            return "EXPIRED"
        return "PENDING"
