from django.core.management.base import BaseCommand
from django.utils import timezone
from maintenance.models import RappelPreventive, Notification
from maintenance.signals import creer_notif


class Command(BaseCommand):
    help = (
        "Envoie les rappels de maintenances préventives dont la date d'envoi prévue "
        "est atteinte et qui n'ont pas encore été envoyés."
    )

    def handle(self, *args, **options):
        rappels = RappelPreventive.objects.filter(envoye_le__isnull=True).select_related(
            'preventive__equipement__site'
        ).prefetch_related('destinataires')

        envoyes = 0
        for rappel in rappels:
            if not rappel.doit_etre_envoye():
                continue

            preventive = rappel.preventive
            destinataires = rappel.destinataires.all()

            if not destinataires.exists():
                # Fallback : agents silo du site
                from django.contrib.auth.models import User
                site = preventive.equipement.site
                destinataires = User.objects.filter(
                    profile__role='silo', profile__sites=site
                )

            msg = rappel.message_personnalise or (
                f"Rappel maintenance préventive : {preventive.titre}\n"
                f"Équipement : {preventive.equipement}\n"
                f"Échéance : {preventive.date_echeance} ({rappel.get_delai_display()})"
            )
            lien = f'/preventives/{preventive.pk}/'
            for user in destinataires:
                creer_notif(
                    user,
                    Notification.TYPE_PREVENTIVE,
                    f'Rappel préventive : {preventive.titre}',
                    msg,
                    lien,
                )

            rappel.envoye_le = timezone.now()
            rappel.save(update_fields=['envoye_le'])
            envoyes += 1

        self.stdout.write(self.style.SUCCESS(f"{envoyes} rappel(s) envoyé(s)."))
