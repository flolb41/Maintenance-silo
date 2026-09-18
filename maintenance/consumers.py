import json

from channels.generic.websocket import AsyncWebsocketConsumer


class RealtimeConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            await self.close()
            return
        self.groupe = f"maintenance_user_{user.pk}"
        await self.channel_layer.group_add(self.groupe, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        groupe = getattr(self, "groupe", None)
        if groupe:
            await self.channel_layer.group_discard(groupe, self.channel_name)

    async def maintenance_event(self, event):
        await self.send(
            text_data=json.dumps(
                {"type": event["event_type"], "data": event["data"]},
                ensure_ascii=False,
            )
        )
