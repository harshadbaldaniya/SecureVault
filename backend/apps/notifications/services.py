"""Create notifications. Rows are written in the caller's transaction (so they exist exactly when the
event committed); real-time delivery is triggered only after commit (wired in by the realtime module)."""

from collections.abc import Callable, Iterable

from django.db import transaction

from .models import Notification

# Real-time push hooks (e.g. WebSocket fan-out). Called after commit with the created notifications.
_after_commit_hooks: list[Callable[[list[Notification]], None]] = []


def register_push_hook(hook: Callable[[list[Notification]], None]) -> None:
    if hook not in _after_commit_hooks:
        _after_commit_hooks.append(hook)


def notify(
    recipients: Iterable,
    type: str,
    title: str,
    message: str = "",
    *,
    priority: str = Notification.Priority.NORMAL,
    link: str = "",
) -> list[Notification]:
    unique = {user.pk: user for user in recipients if user is not None}
    notifications = [
        Notification(
            organization_id=user.organization_id,
            recipient=user,
            type=type,
            priority=priority,
            title=title[:200],
            message=message[:1000],
            link=link[:300],
        )
        for user in unique.values()
    ]
    if not notifications:
        return []
    created = Notification.objects.bulk_create(notifications)

    def push() -> None:
        for hook in list(_after_commit_hooks):
            hook(created)

    transaction.on_commit(push)
    return created
