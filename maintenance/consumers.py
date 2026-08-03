import json
from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope['user']
        if user.is_anonymous:
            await self.close()
            return
        self.user_group = f'user_{user.pk}'
        try:
            role = user.profile.role
            self.role_group = f'role_{role}'
        except Exception:
            self.role_group = None

        await self.channel_layer.group_add(self.user_group, self.channel_name)
        if self.role_group:
            await self.channel_layer.group_add(self.role_group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'user_group'):
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
        if hasattr(self, 'role_group') and self.role_group:
            await self.channel_layer.group_discard(self.role_group, self.channel_name)

    async def receive(self, text_data):
        pass

    async def notification_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'titre': event['titre'],
            'message': event['message'],
            'lien': event.get('lien', ''),
        }))
