"""
Service centralisé pour créer les notifications persistantes
et diffuser les événements WebSocket.
"""
from asgiref.sync import async_to_sync

from .models import Notification


def _diffuser_ws(event_type: str, data: dict):
    """Diffuse un événement WebSocket sur le groupe global (best-effort)."""
    try:
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            "maintenance_global",
            {
                "type": "maintenance.event",
                "event_type": event_type,
                "data": data,
            },
        )
    except Exception:
        # Redis indisponible : ne pas faire échouer la requête
        pass


def notifier(utilisateur, type_notif: str, titre: str, message: str, lien: str = "", ws_data: dict | None = None):
    """Crée une notification persistante et diffuse l'événement WS."""
    notif = Notification.objects.create(
        utilisateur=utilisateur,
        type_notif=type_notif,
        titre=titre,
        message=message,
        lien=lien,
    )
    _diffuser_ws(
        type_notif,
        {
            "id": notif.id,
            "titre": titre,
            "message": message,
            "lien": lien,
            **(ws_data or {}),
        },
    )
    return notif


def notifier_plusieurs(utilisateurs, type_notif: str, titre: str, message: str, lien: str = ""):
    """Crée les notifications pour une liste d'utilisateurs."""
    for u in utilisateurs:
        notifier(u, type_notif, titre, message, lien)
