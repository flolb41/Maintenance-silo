"""
Service centralisé pour créer les notifications persistantes
et diffuser les événements WebSocket.
"""
from asgiref.sync import async_to_sync
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Facture, Notification, PanneTempsIntervention


def synthese_budget_site(site, annee):
    factures = Facture.objects.filter(statut=Facture.STATUT_VALIDE, date_facture__year=annee).filter(
        Q(panne__site=site) | Q(preventive__site=site) | Q(
            preventive__equipement__site=site)
    )
    facture_pannes = factures.filter(panne__isnull=False).aggregate(
        total=Sum("montant_ttc"))["total"] or Decimal("0")
    facture_preventives = factures.filter(panne__isnull=True).aggregate(
        total=Sum("montant_ttc"))["total"] or Decimal("0")
    main_oeuvre = PanneTempsIntervention.objects.filter(
        panne__site=site, validee=True, date_intervention__year=annee).aggregate(total=Sum("montant"))["total"] or Decimal("0")
    return {"facture_pannes": facture_pannes, "facture_preventives": facture_preventives, "main_oeuvre": main_oeuvre, "depense": facture_pannes + facture_preventives + main_oeuvre}


def _diffuser_ws(utilisateur_id: int, event_type: str, data: dict):
    """Diffuse un événement WebSocket au destinataire (best-effort)."""
    try:
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"maintenance_user_{utilisateur_id}",
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
        utilisateur.pk,
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
