from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def diffuser_evenement(event_type, data):
    """Diffuse un événement temps réel vers tous les clients connectés."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "maintenance_global",
        {
            "type": "maintenance.event",
            "event_type": event_type,
            "data": data,
        },
    )
