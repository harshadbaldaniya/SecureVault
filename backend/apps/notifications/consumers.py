"""WebSocket endpoint for real-time events (/ws/events/).

Authentication uses the same server-side session cookie as the API. The handshake re-checks the account,
the organization and any active lockdown, so a client that reconnects during a lockdown cannot bypass it.
Messages are informational; the API enforces everything on its own.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from core.realtime import CLOSE_LOCKDOWN, CLOSE_UNAUTHENTICATED, org_group, user_group


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
        if user is None or not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        state = await database_sync_to_async(_handshake_state)(user)
        if not state["allowed"]:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        await self.accept()
        if state["blocked"]:
            await self.send_json({"type": "lockdown.active", "lockdown": state["blocked"]})
            await self.close(code=CLOSE_LOCKDOWN)
            return
        self.joined = [user_group(state["user_id"]), org_group(state["org_id"])]
        for group in self.joined:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.send_json(
            {"type": "hello", "server_time": timezone.now().isoformat(), "lockdown": state["lockdown"]}
        )

    async def disconnect(self, code):
        for group in self.joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong", "server_time": timezone.now().isoformat()})

    async def event_push(self, event):
        await self.send_json(event["payload"])

    async def event_close(self, event):
        await self.close(code=event.get("code", CLOSE_UNAUTHENTICATED))
