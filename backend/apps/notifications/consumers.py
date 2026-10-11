"""WebSocket endpoint for real-time events (/ws/events/).

Authentication uses the same server-side session cookie as the API. The handshake re-checks the account,
the organization and any active lockdown, so a client that reconnects during a lockdown cannot bypass it.
Messages are informational; the API enforces everything on its own.
"""

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from core.metrics import WEBSOCKET_CONNECTIONS
from core.realtime import CLOSE_LOCKDOWN, CLOSE_UNAUTHENTICATED, CLOSE_UNAVAILABLE, org_group, user_group

logger = logging.getLogger(__name__)


def _handshake_state(user) -> dict:
    from apps.lockdown.services import applicable, payload, session_block

    if not (user.is_active and user.organization.status == "ACTIVE"):
        return {"allowed": False}
    blocked = session_block(user)
    return {
        "allowed": True,
        "blocked": payload(blocked),
        "lockdown": payload(applicable(user)),
        "user_id": str(user.pk),
        "org_id": str(user.organization_id),
    }


class EventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        self.joined: list[str] = []
        self.counted = False
        # Refusals accept first and then close with an application code. Rejecting the handshake itself would
        # surface in browsers as an anonymous 1006, indistinguishable from "server unreachable", and the client
        # would keep retrying. No data is sent before the close.
        if user is None or not user.is_authenticated:
            await self.accept()
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        state = await database_sync_to_async(_handshake_state)(user)
        if not state["allowed"]:
            await self.accept()
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        await self.accept()
        if state["blocked"]:
            await self.send_json({"type": "lockdown.active", "lockdown": state["blocked"]})
            await self.close(code=CLOSE_LOCKDOWN)
            return
        try:
            for group in (user_group(state["user_id"]), org_group(state["org_id"])):
                await self.channel_layer.group_add(group, self.channel_name)
                self.joined.append(group)
        except Exception as exc:  # Redis (the channel layer) is unreachable
            # Real-time is a convenience: the API enforces everything on its own. Close cleanly so the client backs off
            # and retries instead of the socket erroring out of the consumer.
            logger.warning("WebSocket refused: channel layer unavailable (%s)", type(exc).__name__)
            await self.close(code=CLOSE_UNAVAILABLE)
            return
        WEBSOCKET_CONNECTIONS.inc()
        self.counted = True
        await self.send_json(
            {"type": "hello", "server_time": timezone.now().isoformat(), "lockdown": state["lockdown"]}
        )

    async def disconnect(self, code):
        if self.counted:
            WEBSOCKET_CONNECTIONS.dec()
            self.counted = False
        for group in self.joined:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except Exception as exc:  # the layer may have gone away while the socket was open; nothing to clean up then
                logger.warning("Could not leave group on disconnect (%s)", type(exc).__name__)

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong", "server_time": timezone.now().isoformat()})

    async def event_push(self, event):
        await self.send_json(event["payload"])

    async def event_close(self, event):
        await self.close(code=event.get("code", CLOSE_UNAUTHENTICATED))
