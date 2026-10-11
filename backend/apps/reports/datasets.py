"""Report datasets: explicit allow-lists of columns and filters, always scoped to one organization.

Nothing outside these column definitions can ever appear in a report or export. In particular no dataset
exposes ciphertexts, blind indexes, wrapped keys, token hashes or session keys, and the custom report builder
can only pick from these same columns.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import CharField, Count, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.devices.models import AnomalyAlert, Device
from apps.lockdown.models import LockdownState
from apps.policies.models import policy_for
from apps.sharing.models import Share
from apps.vault.models import Credential
from apps.vault.strength import strength_label


class FilterError(ValueError):
    """A filter value was invalid or not available for this report. The message is safe to show."""


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    get: Callable[[Any], Any]


@dataclass
class Filters:
    department: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    user: uuid.UUID | None = None
    service: uuid.UUID | None = None
    actions: list[str] = field(default_factory=list)
    resource: uuid.UUID | None = None
    device_trust: str | None = None
    share_status: str | None = None
    status: str | None = None

    def describe(self) -> dict:
        return {k: (str(v) if not isinstance(v, list) else v) for k, v in self.__dict__.items() if v not in (None, [])}


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    description: str
    columns: tuple[Column, ...]
    filters: frozenset[str]
    statuses: frozenset[str]
    base: Callable[[Any], QuerySet]
    apply: Callable[[QuerySet, Filters, Any], QuerySet]

    def column(self, key: str) -> Column:
        for column in self.columns:
            if column.key == key:
                return column
        raise FilterError(f'Unknown column "{key}" for this report.')


# --------------------------------------------------------------------------- filter parsing

TRUST_STATES = {"TRUSTED", "PENDING", "SUSPENDED", "REVOKED"}
SHARE_STATES = {"active", "expired", "revoked", "consumed"}


def _get(source: Mapping, key: str):
    value = source.get(key)
    return value.strip() if isinstance(value, str) else value


def _uuid(source, key):
    value = _get(source, key)
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise FilterError(f"{key} must be an id.") from None


def _date(source, key):
    value = _get(source, key)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise FilterError(f"{key} must be a date like 2026-10-31.") from None


def parse_filters(source: Mapping, dataset: Dataset) -> Filters:
    raw_actions = source.getlist("action") if hasattr(source, "getlist") else source.get("action") or []
    if isinstance(raw_actions, str):
        raw_actions = raw_actions.split(",")
    actions = [a.strip().upper() for a in raw_actions if a and a.strip()]
    unknown = [a for a in actions if a not in AuditAction.values]
    if unknown:
        raise FilterError(f"Unknown action(s): {', '.join(unknown)}.")

    filters = Filters(
        department=_uuid(source, "department"),
        date_from=_date(source, "date_from"),
        date_to=_date(source, "date_to"),
        user=_uuid(source, "user"),
        service=_uuid(source, "service"),
        actions=actions,
        resource=_uuid(source, "resource"),
        device_trust=(_get(source, "device_trust") or None),
        share_status=(_get(source, "share_status") or None),
        status=(_get(source, "status") or None),
    )
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise FilterError("date_from must not be after date_to.")
    if filters.device_trust and filters.device_trust.upper() not in TRUST_STATES:
        raise FilterError("device_trust must be TRUSTED, PENDING, SUSPENDED or REVOKED.")
    if filters.device_trust:
        filters.device_trust = filters.device_trust.upper()
    if filters.share_status and filters.share_status.lower() not in SHARE_STATES:
        raise FilterError("share_status must be active, expired, revoked or consumed.")
    if filters.share_status:
        filters.share_status = filters.share_status.lower()
    if filters.status and filters.status not in dataset.statuses:
        raise FilterError(f"status must be one of: {', '.join(sorted(dataset.statuses))}.")

    used = {name for name, value in filters.__dict__.items() if value not in (None, [])}
    used = {"date" if name in ("date_from", "date_to") else "action" if name == "actions" else name for name in used}
    unsupported = used - dataset.filters
    if unsupported:
        raise FilterError(f"Not available for this report: {', '.join(sorted(unsupported))}.")
    return filters


def _range(queryset, field_name, filters: Filters):
    if filters.date_from:
        queryset = queryset.filter(
            **{f"{field_name}__gte": timezone.make_aware(datetime.combine(filters.date_from, time.min))}
        )
    if filters.date_to:
        end = timezone.make_aware(datetime.combine(filters.date_to + timedelta(days=1), time.min))
        queryset = queryset.filter(**{f"{field_name}__lt": end})
    return queryset


def _name(user) -> str:
    return user.full_name if user is not None else ""


def _dept(user) -> str:
    return user.department.name if user is not None and user.department_id else ""


# --------------------------------------------------------------------------- 1. audit trail


def _audit_base(org):
    department = User.objects.filter(pk=OuterRef("actor_id")).values("department__name")[:1]
    return (
        AuditLog.objects.filter(organization=org)
        .annotate(actor_department=Subquery(department))
        .order_by("-created_at", "-id")
    )


def _audit_apply(qs, f: Filters, org):
    qs = _range(qs, "created_at", f)
    if f.user:
        qs = qs.filter(actor_id=f.user)
    if f.department:
        qs = qs.filter(actor_id__in=User.objects.filter(organization=org, department_id=f.department).values("pk"))
    if f.actions:
        qs = qs.filter(action__in=f.actions)
    if f.resource:
        qs = qs.filter(target_id=str(f.resource))
    if f.service:
        ids = Credential.objects.filter(organization=org, service_id=f.service).annotate(sid=Cast("pk", CharField()))
        qs = qs.filter(target_type="credential", target_id__in=ids.values("sid"))
    if f.device_trust:
        qs = qs.filter(metadata__device__trust=f.device_trust)
    if f.status:
        qs = qs.filter(outcome=f.status)
    return qs


AUDIT = Dataset(
    key="audit",
    title="Audit trail compliance",
    description="Chronological record of sign-ins, reveals, copies, edits, shares, revocations and lockdowns.",
    columns=(
        Column("created_at", "Time (UTC)", lambda r: r.created_at),
        Column("sequence", "Record #", lambda r: r.sequence),
        Column("action", "Action", lambda r: r.action),
        Column("outcome", "Outcome", lambda r: r.outcome),
        Column("actor_email", "Actor", lambda r: r.actor_email),
        Column("actor_department", "Actor department", lambda r: r.actor_department or ""),
        Column("target_type", "Target type", lambda r: r.target_type),
        Column("target_label", "Target", lambda r: r.target_label),
        Column("target_id", "Target id", lambda r: r.target_id),
        Column("ip_address", "IP address", lambda r: r.ip_address or ""),
        Column("device_trust", "Device trust", lambda r: ((r.metadata or {}).get("device") or {}).get("trust", "")),
        Column("reason", "Reason", lambda r: r.reason),
        Column("request_id", "Request id", lambda r: r.request_id),
    ),
    filters=frozenset({"date", "user", "department", "action", "resource", "service", "device_trust", "status"}),
    statuses=frozenset(AuditOutcome.values),
    base=_audit_base,
    apply=_audit_apply,
)


# --------------------------------------------------------------------------- 2. credential hygiene

WEAK_BITS = 36
EXPIRING_DAYS = 30


def _credentials_base(org):
    same_secret = (
        Credential.objects.filter(
            organization=OuterRef("organization"),
            blind_index=OuterRef("blind_index"),
            blind_index_version=OuterRef("blind_index_version"),
            archived_at__isnull=True,
        )
        .values("organization")
        .annotate(n=Count("pk"))
        .values("n")
    )
    live_shares = (
        Share.objects.filter(
            credential=OuterRef("pk"), revoked_at__isnull=True, burned_at__isnull=True, expires_at__gt=timezone.now()
        )
        .values("credential")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return (
        Credential.objects.filter(organization=org, archived_at__isnull=True)
        .select_related("owner__department", "service")
        .annotate(
            reuse_group_size=Coalesce(Subquery(same_secret, output_field=IntegerField()), 1),
            active_shares=Coalesce(Subquery(live_shares, output_field=IntegerField()), 0),
        )
        .order_by("title", "id")
    )


def _credentials_apply(qs, f: Filters, org):
    qs = _range(qs, "created_at", f)
    if f.department:
        qs = qs.filter(owner__department_id=f.department)
    if f.user:
        qs = qs.filter(owner_id=f.user)
    if f.service:
        qs = qs.filter(service_id=f.service)
    if f.resource:
        qs = qs.filter(pk=f.resource)
    today = timezone.localdate()
    if f.status == "weak":
        qs = qs.filter(entropy_bits__lt=WEAK_BITS)
    elif f.status == "expired":
        qs = qs.filter(expires_at__lt=today)
    elif f.status == "expiring":
        qs = qs.filter(expires_at__gte=today, expires_at__lte=today + timedelta(days=EXPIRING_DAYS))
    elif f.status == "reused":
        qs = qs.filter(reuse_group_size__gt=1)
    elif f.status == "stale":
        max_age = policy_for(org).max_password_age_days or 365
        qs = qs.filter(password_changed_at__lt=timezone.now() - timedelta(days=max_age))
    return qs


CREDENTIALS = Dataset(
    key="credentials",
    title="Credential hygiene and exposure",
    description="Weak, expired, expiring, stale and reused credentials. Metadata only; secrets never leave the vault.",
    columns=(
        Column("title", "Credential", lambda r: r.title),
        Column("owner", "Owner", lambda r: _name(r.owner)),
        Column("owner_email", "Owner email", lambda r: r.owner.email),
        Column("department", "Department", lambda r: _dept(r.owner)),
        Column("service", "Service", lambda r: r.service.name if r.service_id else ""),
        Column("secret_type", "Type", lambda r: r.secret_type),
        Column("strength", "Strength", lambda r: strength_label(r.entropy_bits)),
        Column("entropy_bits", "Entropy (bits, estimate)", lambda r: round(r.entropy_bits)),
        Column("password_age_days", "Age (days)", lambda r: (timezone.now() - r.password_changed_at).days),
        Column("expires_at", "Expires", lambda r: r.expires_at),
        Column("expired", "Expired", lambda r: bool(r.expires_at and r.expires_at < timezone.localdate())),
        Column("reuse_group_size", "Credentials sharing this secret", lambda r: r.reuse_group_size),
        Column("active_shares", "Active shares", lambda r: r.active_shares),
        Column("created_at", "Created (UTC)", lambda r: r.created_at),
    ),
    filters=frozenset({"date", "department", "user", "service", "resource", "status"}),
    statuses=frozenset({"weak", "expired", "expiring", "reused", "stale"}),
    base=_credentials_base,
    apply=_credentials_apply,
)


# --------------------------------------------------------------------------- 3. device posture


def _devices_base(org):
    return Device.objects.filter(organization=org).select_related("user__department").order_by("-last_seen_at", "id")


def _devices_apply(qs, f: Filters, org):
    qs = _range(qs, "last_seen_at", f)
    if f.department:
        qs = qs.filter(user__department_id=f.department)
    if f.user:
        qs = qs.filter(user_id=f.user)
    if f.device_trust:
        qs = qs.filter(trust_state=f.device_trust)
    return qs


DEVICES = Dataset(
    key="devices",
    title="Device access and posture",
    description="Registered devices, their trust state and when they were last seen.",
    columns=(
        Column("name", "Device", lambda r: r.name),
        Column("user", "Person", lambda r: _name(r.user)),
        Column("user_email", "Email", lambda r: r.user.email),
        Column("department", "Department", lambda r: _dept(r.user)),
        Column("os", "OS", lambda r: r.os),
        Column("browser", "Browser", lambda r: r.browser),
        Column("trust_state", "Trust", lambda r: r.trust_state),
        Column("last_seen_at", "Last seen (UTC)", lambda r: r.last_seen_at),
        Column("last_ip", "Last IP", lambda r: r.last_ip or ""),
        Column("first_ip", "First IP", lambda r: r.first_ip or ""),
        Column("created_at", "Registered (UTC)", lambda r: r.created_at),
    ),
    filters=frozenset({"date", "department", "user", "device_trust"}),
    statuses=frozenset(),
    base=_devices_base,
    apply=_devices_apply,
)


# --------------------------------------------------------------------------- 4. delegation


def _shares_base(org):
    return (
        Share.objects.filter(organization=org)
        .select_related("credential__service", "grantor", "grantee__department")
        .order_by("credential__title", "depth", "created_at")
    )


def _shares_apply(qs, f: Filters, org):
    qs = _range(qs, "created_at", f)
    now = timezone.now()
    if f.share_status == "active":
        qs = qs.filter(revoked_at__isnull=True, burned_at__isnull=True, expires_at__gt=now)
    elif f.share_status == "expired":
        qs = qs.filter(revoked_at__isnull=True, burned_at__isnull=True, expires_at__lte=now)
    elif f.share_status == "revoked":
        qs = qs.filter(revoked_at__isnull=False)
    elif f.share_status == "consumed":
        qs = qs.filter(burned_at__isnull=False)
    if f.user:
        qs = qs.filter(Q(grantor_id=f.user) | Q(grantee_id=f.user))
    if f.resource:
        qs = qs.filter(credential_id=f.resource)
    if f.service:
        qs = qs.filter(credential__service_id=f.service)
    if f.department:
        qs = qs.filter(grantee__department_id=f.department)
    return qs


SHARES = Dataset(
    key="shares",
    title="Access delegation",
    description="Every grant with its grantor, grantee, permission, expiry and place in the delegation tree.",
    columns=(
        Column("credential", "Credential", lambda r: r.credential.title),
        Column("service", "Service", lambda r: r.credential.service.name if r.credential.service_id else ""),
        Column("grantor", "Grantor", lambda r: _name(r.grantor)),
        Column("grantee", "Grantee", lambda r: _name(r.grantee)),
        Column("grantee_department", "Grantee department", lambda r: _dept(r.grantee)),
        Column("permission", "Permission", lambda r: r.permission),
        Column("depth", "Delegation level", lambda r: r.depth),
        Column("parent_share", "Parent grant", lambda r: str(r.parent_share_id or "")),
        Column("state", "Status", lambda r: r.state(timezone.now())),
        Column("view_once", "View once", lambda r: r.is_view_once),
        Column("expires_at", "Expires (UTC)", lambda r: r.expires_at),
        Column("created_at", "Granted (UTC)", lambda r: r.created_at),
        Column("revoked_at", "Revoked (UTC)", lambda r: r.revoked_at),
        Column("revoke_reason", "Revocation reason", lambda r: r.revoke_reason),
        Column("id", "Grant id", lambda r: str(r.pk)),
        Column("credential_id", "Credential id", lambda r: str(r.credential_id)),
    ),
    filters=frozenset({"date", "share_status", "user", "resource", "service", "department"}),
    statuses=frozenset(),
    base=_shares_base,
    apply=_shares_apply,
)


# --------------------------------------------------------------------------- 5. incidents


def _lockdowns_base(org):
    return (
        LockdownState.objects.filter(organization=org)
        .select_related("target_user", "initiated_by", "resolved_by")
        .order_by("-created_at")
    )


def _lockdowns_apply(qs, f: Filters, org):
    qs = _range(qs, "created_at", f)
    if f.user:
        qs = qs.filter(Q(initiated_by_id=f.user) | Q(target_user_id=f.user))
    if f.status == "active":
        qs = qs.filter(is_active=True)
    elif f.status == "resolved":
        qs = qs.filter(is_active=False)
    return qs


LOCKDOWNS = Dataset(
    key="lockdowns",
    title="Incidents and lockdowns",
    description="Lockdown history: who started it, scope, reason, sessions ended and how it was resolved.",
    columns=(
        Column("triggered_at", "Started (UTC)", lambda r: r.created_at),
        Column("scope", "Scope", lambda r: r.scope),
        Column("target_user", "Target account", lambda r: _name(r.target_user)),
        Column("reason", "Reason", lambda r: r.reason),
        Column("initiated_by", "Initiated by", lambda r: _name(r.initiated_by)),
        Column("terminated_session_count", "Sessions ended", lambda r: r.terminated_session_count),
        Column("status", "Status", lambda r: "active" if r.is_active else "resolved"),
        Column("resolved_at", "Resolved (UTC)", lambda r: r.resolved_at),
        Column("resolved_by", "Resolved by", lambda r: _name(r.resolved_by)),
        Column("resolution_note", "Resolution", lambda r: r.resolution_note),
    ),
    filters=frozenset({"date", "user", "status"}),
    statuses=frozenset({"active", "resolved"}),
    base=_lockdowns_base,
    apply=_lockdowns_apply,
)


# --------------------------------------------------------------------------- alerts (custom builder)


def _alerts_base(org):
    return (
        AnomalyAlert.objects.filter(organization=org)
        .select_related("user__department", "reviewed_by")
        .order_by("-created_at")
    )


def _alerts_apply(qs, f: Filters, org):
    qs = _range(qs, "created_at", f)
    if f.user:
        qs = qs.filter(user_id=f.user)
    if f.department:
        qs = qs.filter(user__department_id=f.department)
    if f.status:
        qs = qs.filter(status=f.status)
    return qs


ALERTS = Dataset(
    key="alerts",
    title="Security alerts",
    description="Anomaly alerts raised by the rule-based detector and how they were reviewed.",
    columns=(
        Column("created_at", "Raised (UTC)", lambda r: r.created_at),
        Column("type", "Type", lambda r: r.type),
        Column("severity", "Severity", lambda r: r.severity),
        Column("status", "Status", lambda r: r.status),
        Column("summary", "Summary", lambda r: r.summary),
        Column("user", "Person", lambda r: _name(r.user)),
        Column("department", "Department", lambda r: _dept(r.user)),
        Column("ip_address", "IP", lambda r: r.ip_address or ""),
        Column("reviewed_by", "Reviewed by", lambda r: _name(r.reviewed_by)),
        Column("review_note", "Review note", lambda r: r.review_note),
    ),
    filters=frozenset({"date", "user", "department", "status"}),
    statuses=frozenset(AnomalyAlert.Status.values),
    base=_alerts_base,
    apply=_alerts_apply,
)


DATASETS: dict[str, Dataset] = {d.key: d for d in (AUDIT, CREDENTIALS, DEVICES, SHARES, LOCKDOWNS, ALERTS)}
