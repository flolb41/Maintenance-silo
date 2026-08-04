"""
Signaux Django pour les notifications automatiques.
Utiliser des flags sur les instances pour éviter les doublons
lors des post_save successifs.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Facture, MaintenancePreventive, Notification, Panne, PanneMedia, PreventiveMedia


# ---------------------------------------------------------------------------
# Pannes
# ---------------------------------------------------------------------------

@receiver(pre_save, sender=Panne)
def panne_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._ancien_statut = Panne.objects.values_list("statut", flat=True).get(pk=instance.pk)
        except Panne.DoesNotExist:
            instance._ancien_statut = None
    else:
        instance._ancien_statut = None


@receiver(post_save, sender=Panne)
def panne_post_save(sender, instance, created, **kwargs):
    from .services import notifier, notifier_plusieurs
    from django.contrib.auth import get_user_model

    User = get_user_model()

    if created:
        # Notifier les admins et agents maintenance du site
        destinataires = list(
            User.objects.filter(
                sites_autorises=instance.site,
                profile__role__in=["admin", "maintenance"],
            ).distinct()
        )
        notifier_plusieurs(
            destinataires,
            Notification.TypeNotif.PANNE_CREEE,
            f"Nouvelle panne : {instance.titre}",
            f"Panne déclarée par {instance.declarant.get_full_name() or instance.declarant.username} sur {instance.site.nom}.",
            lien=f"/pannes/{instance.pk}/",
        )
        return

    ancien = getattr(instance, "_ancien_statut", None)
    if ancien is None or ancien == instance.statut:
        return

    if instance.agent_assigne and instance.statut == Panne.Statut.AFFECTEE:
        notifier(
            instance.agent_assigne,
            Notification.TypeNotif.PANNE_AFFECTEE,
            f"Panne affectée : {instance.titre}",
            f"La panne « {instance.titre} » vous a été affectée sur {instance.site.nom}.",
            lien=f"/pannes/{instance.pk}/",
        )
    else:
        # Notifier le déclarant du changement de statut
        notifier(
            instance.declarant,
            Notification.TypeNotif.PANNE_STATUT,
            f"Panne mise à jour : {instance.titre}",
            f"Statut passé de « {ancien} » à « {instance.statut} ».",
            lien=f"/pannes/{instance.pk}/",
        )


# ---------------------------------------------------------------------------
# Maintenances préventives
# ---------------------------------------------------------------------------

@receiver(pre_save, sender=MaintenancePreventive)
def preventive_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._ancien_statut = MaintenancePreventive.objects.values_list(
                "statut", flat=True
            ).get(pk=instance.pk)
        except MaintenancePreventive.DoesNotExist:
            instance._ancien_statut = None
    else:
        instance._ancien_statut = None


@receiver(post_save, sender=MaintenancePreventive)
def preventive_post_save(sender, instance, created, **kwargs):
    from .services import notifier

    if created:
        return

    ancien = getattr(instance, "_ancien_statut", None)
    if ancien is None or ancien == instance.statut:
        return

    S = MaintenancePreventive.Statut
    N = Notification.TypeNotif

    mapping = {
        S.ENVOYEE: (
            instance.destinataire,
            N.PREVENTIVE_RECUE,
            f"Tâche reçue : {instance.titre}",
            f"L'agent {instance.createur.get_full_name() or instance.createur.username} vous a envoyé une tâche : {instance.titre}.",
        ),
        S.EN_COURS: (
            instance.createur,
            N.PREVENTIVE_DEMARREE,
            f"Tâche démarrée : {instance.titre}",
            f"L'agent {instance.destinataire.get_full_name() or instance.destinataire.username} a démarré la tâche {instance.titre}.",
        ),
        S.A_VALIDER: (
            instance.createur,
            N.PREVENTIVE_TERMINEE,
            f"Tâche terminée – à valider : {instance.titre}",
            f"La tâche « {instance.titre} » est terminée et attend votre validation.",
        ),
        S.VALIDEE: (
            instance.destinataire,
            N.PREVENTIVE_VALIDEE,
            f"Tâche validée : {instance.titre}",
            f"Votre tâche « {instance.titre} » a été validée.",
        ),
        S.REJETEE: (
            instance.destinataire,
            N.PREVENTIVE_REJETEE,
            f"Tâche rejetée : {instance.titre}",
            f"Votre tâche « {instance.titre} » a été rejetée. Commentaire : {instance.commentaire_validation}",
        ),
        S.EN_RETARD: (
            instance.destinataire,
            N.PREVENTIVE_RETARD,
            f"Tâche en retard : {instance.titre}",
            f"La tâche « {instance.titre} » n'a pas été effectuée avant l'échéance.",
        ),
    }

    entry = mapping.get(instance.statut)
    if entry:
        utilisateur, type_notif, titre, message = entry
        notifier(utilisateur, type_notif, titre, message, lien=f"/preventives/{instance.pk}/")


# ---------------------------------------------------------------------------
# Médias
# ---------------------------------------------------------------------------

@receiver(post_save, sender=PanneMedia)
def panne_media_post_save(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import notifier
    from django.contrib.auth import get_user_model

    User = get_user_model()
    panne = instance.panne
    destinataires = {panne.declarant}
    if panne.agent_assigne:
        destinataires.add(panne.agent_assigne)
    for u in User.objects.filter(
        sites_autorises=panne.site, profile__role__in=["admin", "maintenance"]
    ).distinct():
        destinataires.add(u)

    destinataires.discard(instance.ajoute_par)
    for u in destinataires:
        notifier(
            u,
            Notification.TypeNotif.MEDIA_AJOUTE,
            f"Média ajouté – {panne.titre}",
            f"Un nouveau fichier a été ajouté à la panne « {panne.titre} ».",
            lien=f"/pannes/{panne.pk}/",
        )


@receiver(post_save, sender=PreventiveMedia)
def preventive_media_post_save(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import notifier

    preventive = instance.preventive
    for u in {preventive.createur, preventive.destinataire} - {instance.ajoute_par}:
        notifier(
            u,
            Notification.TypeNotif.MEDIA_AJOUTE,
            f"Média ajouté – {preventive.titre}",
            f"Un nouveau fichier a été ajouté à la tâche « {preventive.titre} ».",
            lien=f"/preventives/{preventive.pk}/",
        )


# ---------------------------------------------------------------------------
# Factures
# ---------------------------------------------------------------------------

@receiver(post_save, sender=Facture)
def facture_post_save(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import notifier
    from django.contrib.auth import get_user_model

    User = get_user_model()
    panne = instance.panne
    admins = list(
        User.objects.filter(
            sites_autorises=panne.site, profile__role="admin"
        ).distinct()
    )
    for u in admins:
        notifier(
            u,
            Notification.TypeNotif.FACTURE_AJOUTEE,
            f"Nouvelle facture – {panne.titre}",
            f"Facture {instance.numero} ({instance.montant_ttc} € TTC) ajoutée par {User.objects.filter(pannes_assignees=panne).first() or 'inconnu'}.",
            lien=f"/pannes/{panne.pk}/",
        )
