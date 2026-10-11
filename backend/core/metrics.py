"""Operational metrics in Prometheus text format, served by `core.views.MetricsView`.

What is exposed, and what is not:
- HTTP request counts and latencies for this process, labelled by method, URL *pattern* and status. The pattern
  (never the raw path) keeps label cardinality bounded and keeps ids out of the metrics.
- Aggregate gauges read from PostgreSQL at scrape time: counts by status/severity across all organizations.
  No organization, user, credential or token appears as a label or a value.

Counters are per process (one Daphne process per container); scrape each instance and let Prometheus aggregate.
"""

import logging

from django.utils import timezone
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "sv_http_requests_total",
    "HTTP requests handled by this process.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_SECONDS = Histogram(
    "sv_http_request_duration_seconds",
    "Time spent handling HTTP requests in this process.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
WEBSOCKET_CONNECTIONS = Gauge(
    "sv_websocket_connections",
    "Authenticated WebSocket connections currently open in this process.",
    registry=REGISTRY,
)

UNMATCHED_ROUTE = "unmatched"


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_SECONDS.labels(method, route).observe(seconds)


def _grouped(family: GaugeMetricFamily, rows, label_values: tuple[str, ...]) -> None:
    """Fill a labelled gauge, emitting a zero for every expected value so a series never disappears."""
    counts = {value: 0 for value in label_values}
    counts.update({value: count for value, count in rows})
    for value, count in counts.items():
        family.add_metric([value], count)


class DatabaseGauges:
    """Computed on every scrape. Cheap aggregate queries only; no row-level data is read."""

    def describe(self):
        # Declared (empty) so the registry does not call collect() at import time, which would query the database.
        return []

    def collect(self):
        from django.contrib.sessions.models import Session
        from django.db.models import Count, Sum

        from apps.accounts.models import User
        from apps.audit.models import AuditChainHead
        from apps.devices.models import AnomalyAlert, Device
        from apps.imports.models import ImportJob
        from apps.lockdown.models import LockdownState
        from apps.organizations.models import Organization
        from apps.sharing.models import Share

        up = GaugeMetricFamily("sv_database_up", "1 if the metrics scrape could query PostgreSQL.")
        try:
            now = timezone.now()
            users = GaugeMetricFamily("sv_users", "Users by status.", labels=["status"])
            _grouped(
                users,
                User.objects.values_list("status").annotate(n=Count("id")).order_by(),
                tuple(User.Status.values),
            )
            organizations = GaugeMetricFamily("sv_organizations", "Organizations by status.", labels=["status"])
            _grouped(
                organizations,
                Organization.objects.values_list("status").annotate(n=Count("id")).order_by(),
                tuple(Organization.Status.values),
            )
            devices = GaugeMetricFamily("sv_devices", "Devices by trust state.", labels=["trust_state"])
            _grouped(
                devices,
                Device.objects.values_list("trust_state").annotate(n=Count("id")).order_by(),
                tuple(Device.Trust.values),
            )
            alerts = GaugeMetricFamily("sv_open_alerts", "Open anomaly alerts by severity.", labels=["severity"])
            _grouped(
                alerts,
                AnomalyAlert.objects.filter(status=AnomalyAlert.Status.OPEN)
                .values_list("severity")
                .annotate(n=Count("id"))
                .order_by(),
                tuple(AnomalyAlert.Severity.values),
            )
            imports = GaugeMetricFamily("sv_import_jobs", "Employee import jobs by status.", labels=["status"])
            _grouped(
                imports,
                ImportJob.objects.values_list("status").annotate(n=Count("id")).order_by(),
                tuple(ImportJob.Status.values),
            )
            lockdowns = GaugeMetricFamily("sv_active_lockdowns", "Emergency lockdowns currently active.")
            lockdowns.add_metric([], LockdownState.objects.filter(is_active=True).count())
            shares = GaugeMetricFamily("sv_active_shares", "Share grants that are currently usable.")
            shares.add_metric(
                [],
                Share.objects.filter(revoked_at__isnull=True, burned_at__isnull=True, expires_at__gt=now).count(),
            )
            sessions = GaugeMetricFamily("sv_sessions", "Unexpired server-side sessions.")
            sessions.add_metric([], Session.objects.filter(expire_date__gt=now).count())
            # The sum of per-chain head sequences is the number of audit records ever written: it avoids
            # counting a table that only grows.
            audit_total = AuditChainHead.objects.aggregate(total=Sum("last_sequence"))["total"] or 0
            audit = GaugeMetricFamily("sv_audit_records", "Audit records written (all chains).")
            audit.add_metric([], audit_total)
            up.add_metric([], 1)
            yield from (users, organizations, devices, alerts, imports, lockdowns, shares, sessions, audit, up)
        except Exception:
            logger.exception("Metrics scrape: database query failed")
            up.add_metric([], 0)
            yield up


REGISTRY.register(DatabaseGauges())


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
