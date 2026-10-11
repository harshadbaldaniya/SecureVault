"""Employee import jobs: validate, create invitations, report row-level results, retry failed rows."""

import hashlib
import logging
import os

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.accounts import services as accounts
from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.departments.models import Department
from apps.notifications.models import Notification
from apps.notifications.services import notify
from core.exceptions import ServiceError

from .models import ImportJob
from .parser import FileRejected, ParsedRow, check_upload, parse_rows, validate_rows

logger = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "upload.xlsx").replace("\x00", "")
    return base[:255] or "upload.xlsx"


def _send_invitation(email: str, full_name: str, organization_name: str, raw_token: str) -> None:
    link = accounts.invitation_url(raw_token)
    send_mail(
        f"You're invited to {organization_name} on SecureVault",
        f"Hello {full_name},\n\nActivate your SecureVault account within {settings.INVITATION_TTL_HOURS} hours:\n\n"
        f"{link}\n\nIf you were not expecting this, ignore this email.",
        None,
        [email],
    )


def start_import(
    *, actor: User, file_name: str, data: bytes, retry_of: ImportJob | None = None, rows: list[ParsedRow] | None = None
) -> ImportJob:
    """Create a job from an upload (or from a previous job's failed rows). Small jobs run immediately;
    larger ones are queued for the worker."""
    job = ImportJob.objects.create(
        organization=actor.organization,
        uploaded_by=actor,
        file_name=_safe_name(file_name),
        file_sha256=hashlib.sha256(data).hexdigest() if data else "",
        retry_of=retry_of,
    )
    try:
        if rows is None:
            check_upload(file_name, data)
            rows = parse_rows(data)
    except FileRejected as rejected:
        job.status = ImportJob.Status.FAILED
        job.file_error = str(rejected)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "file_error", "finished_at", "updated_at"])
        audit.record(
            AuditAction.EMPLOYEE_IMPORT,
            actor=actor,
            target=job,
            target_type="import_job",
            outcome="FAILURE",
            reason="file_rejected",
            metadata={"file_name": job.file_name},
        )
        return job

    job.total_rows = len(rows)
    job.pending_rows = [r.as_dict() for r in rows]
    job.save(update_fields=["total_rows", "pending_rows", "updated_at"])
    if len(rows) <= settings.IMPORT_SYNC_ROW_LIMIT:
        process(job)
        job.refresh_from_db()
    return job


def process(job: ImportJob) -> ImportJob:
    """Validate and import the job's pending rows. Each row commits on its own, so one bad row never undoes
    the others, and email uniqueness in the database makes duplicate accounts impossible even on retry."""
    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(pk=job.pk)
        if job.status not in (ImportJob.Status.QUEUED,):
            return job
        job.status = ImportJob.Status.PROCESSING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at", "updated_at"])

    actor = job.uploaded_by
    organization = job.organization
    rows = [ParsedRow(**{**r, "errors": []}) for r in job.pending_rows]
    validate_rows(rows, organization)
    departments = {d.code: d for d in Department.objects.filter(organization=organization, status="ACTIVE")}
    errors, succeeded = [], 0

    for row in rows:
        if row.errors:
            errors.append(row.as_dict())
            continue
        try:
            with transaction.atomic():
                _, raw_token = accounts.invite_user(
                    inviter=actor,
                    email=row.email,
                    full_name=row.full_name,
                    role=User.Role.EMPLOYEE,
                    department=departments.get(row.department),
                )
                email, name, org_name = row.email, row.full_name, organization.name
                transaction.on_commit(lambda e=email, n=name, o=org_name, t=raw_token: _send_invitation(e, n, o, t))
            succeeded += 1
        except ServiceError as exc:
            row.errors.append({"field": "email", "message": str(exc.detail)})
            errors.append(row.as_dict())
        except Exception:
            logger.exception("Import job %s: unexpected error on row %s", job.pk, row.row)
            row.errors.append({"field": "", "message": "Unexpected error. Retry this row."})
            errors.append(row.as_dict())

    with transaction.atomic():
        job.success_count = succeeded
        job.failed_count = len(errors)
        job.errors = errors
        job.pending_rows = []  # no personal data kept beyond what the row-level report needs
        job.status = ImportJob.Status.COMPLETED
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "success_count",
                "failed_count",
                "errors",
                "pending_rows",
                "status",
                "finished_at",
                "updated_at",
            ]
        )
        audit.record(
            AuditAction.EMPLOYEE_IMPORT,
            actor=actor,
            target=job,
            target_type="import_job",
            metadata={
                "file_name": job.file_name,
                "total": job.total_rows,
                "succeeded": succeeded,
                "failed": len(errors),
                "retry_of": str(job.retry_of_id) if job.retry_of_id else None,
            },
        )
        notify(
            [actor],
            Notification.Type.IMPORT_COMPLETED,
            f'Import of "{job.file_name}" finished',
            f"{succeeded} invited, {len(errors)} failed.",
            link="/imports",
        )
    return job


def retry_failed(*, actor: User, job: ImportJob) -> ImportJob:
    if job.status != ImportJob.Status.COMPLETED or not job.errors:
        raise ServiceError("Only finished imports with failed rows can be retried.", "nothing_to_retry")
    rows = [
        ParsedRow(
            row=e["row"],
            email=e["email"],
            full_name=e["full_name"],
            department=e.get("department", ""),
            role=e.get("role", ""),
        )
        for e in job.errors
    ]
    return start_import(actor=actor, file_name=job.file_name, data=b"", retry_of=job, rows=rows)


def run_queued(limit: int = 5) -> int:
    """Worker entry point: process queued jobs. SKIP LOCKED lets several workers share the queue."""
    processed = 0
    for _ in range(limit):
        with transaction.atomic():
            job = (
                ImportJob.objects.select_for_update(skip_locked=True)
                .filter(status=ImportJob.Status.QUEUED)
                .order_by("created_at")
                .first()
            )
            if job is None:
                break
            job_id = job.pk
        process(ImportJob.objects.get(pk=job_id))
        processed += 1
    return processed
