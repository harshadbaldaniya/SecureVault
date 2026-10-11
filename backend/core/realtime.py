"""Server -> browser real-time events over Django Channels (Redis channel layer in deployment).

These are NOTIFICATIONS ONLY. Every security decision (lockdown, revocation, device trust) is enforced on
the server for each request; a lost or delayed message can never grant access. Delivery failures are logged
and swallowed so a channel-layer outage cannot break the request that triggered the event.

Groups: "user.<uuid>" (all sockets of one user) and "org.<uuid>" (all sockets in an organization).
"""

import logging
from collections.abc import Iterable

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

CLOSE_UNAUTHENTICATED = 4401
CLOSE_LOCKDOWN = 4423


def user_group(user_id) -> str:
    return f"user.{user_id}"


def org_group(organization_id) -> str:
    return f"org.{organization_id}"


def _send(group: str, message: dict) -> None:
    try:
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(group, message)
    except Exception:
        logger.exception("Real-time delivery to %s failed", group)


def push_to_user(user_id, payload: dict) -> None:
    _send(user_group(user_id), {"type": "event.push", "payload": payload})


def push_to_org(organization_id, payload: dict) -> None:
    _send(org_group(organization_id), {"type": "event.push", "payload": payload})


def close_user_sockets(user_ids: Iterable, code: int = CLOSE_UNAUTHENTICATED) -> None:
    for user_id in set(user_ids):
        _send(user_group(user_id), {"type": "event.close", "code": code})
