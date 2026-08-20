from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Panne, MaintenancePreventive, Facture, Notification
from django.contrib.auth.models import User


def envoyer_notification_ws(user, titre, message, lien=''):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f'user_{user.pk}',
            {
                'type': 'notification_message',
                'titre': titre,
                'message': message,
                'lien': lien,
            }
        )
    except Exception:
        pass


def creer_notif(destinataire, type_notif, titre, message, lien=''):
    notif = Notification.objects.create(
        destinataire=destinataire,
        type_notif=type_notif,
        titre=titre,
        message=message,
        lien=lien,
    )
    envoyer_notification_ws(destinataire, titre, message, lien)
    return notif


@receiver(post_save, sender=Panne)
def notifier_panne(sender, instance, created, **kwargs):
    if created:
        lien = f'/pannes/{instance.pk}/'
        # Notifier les admins et l'équipe maintenance
        admins = User.objects.filter(profile__role__in=['admin', 'maintenance'])
        for user in admins:
            if user != instance.signale_par:
                creer_notif(
                    user,
                    Notification.TYPE_PANNE,
                    f'Nouvelle panne : {instance.titre}',
                    f'Panne signalée sur {instance.equipement} — Priorité : {instance.get_priorite_display()}',
                    lien,
                )
    elif instance.affecte_a:
        lien = f'/pannes/{instance.pk}/'
        # Notifier la personne affectée
        creer_notif(
            instance.affecte_a,
            Notification.TYPE_AFFECTATION,
            f'Panne affectée : {instance.titre}',
            f'Vous êtes affecté à la panne : {instance.titre}',
            lien,
        )


@receiver(post_save, sender=MaintenancePreventive)
def notifier_preventive(sender, instance, created, **kwargs):
    if created:
        lien = f'/preventives/{instance.pk}/'
        # Notifier les admins
        admins = User.objects.filter(profile__role='admin')
        for user in admins:
            creer_notif(
                user,
                Notification.TYPE_PREVENTIVE,
                f'Nouvelle préventive : {instance.titre}',
                f'Échéance le {instance.date_echeance}',
                lien,
            )
        # Notifier les agents silo du même site
        site = instance.equipement.site
        agents_silo = User.objects.filter(profile__role='silo', profile__sites=site)
        for user in agents_silo:
            creer_notif(
                user,
                Notification.TYPE_PREVENTIVE,
                f'Maintenance préventive planifiée : {instance.titre}',
                f'Équipement : {instance.equipement} — Échéance le {instance.date_echeance}',
                lien,
            )


@receiver(post_save, sender=Facture)
def notifier_facture(sender, instance, created, **kwargs):
    if created:
        lien = f'/factures/{instance.pk}/'
        admins = User.objects.filter(profile__role='admin')
        for user in admins:
            creer_notif(
                user,
                Notification.TYPE_FACTURE,
                f'Nouvelle facture : {instance.numero}',
                f'Facture de {instance.fournisseur} — {instance.montant_ttc} € TTC',
                lien,
            )
