import json

from channels.generic.websocket import AsyncWebsocketConsumer


class RealtimeConsumer(AsyncWebsocketConsumer):
    groupe = "maintenance_global"

    async def connect(self):
        utilisateur = self.scope["user"]

        if utilisateur.is_anonymous:
            await self.close()
            return

        await self.channel_layer.group_add(
            self.groupe,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.groupe,
            self.channel_name,
        )

    async def maintenance_event(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": event["event_type"],
                    "data": event["data"],
                },
                ensure_ascii=False,
            )
        )
