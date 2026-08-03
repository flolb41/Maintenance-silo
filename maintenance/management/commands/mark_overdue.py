from django.core.management.base import BaseCommand
from django.utils import timezone
from maintenance.models import MaintenancePreventive


class Command(BaseCommand):
    help = "Passe à 'en_retard' toutes les maintenances préventives dont l'échéance est dépassée."

    def handle(self, *args, **options):
        today = timezone.now().date()
        qs = MaintenancePreventive.objects.filter(
            date_echeance__lt=today,
            statut=MaintenancePreventive.STATUT_PLANIFIEE,
        )
        count = qs.count()
        qs.update(statut=MaintenancePreventive.STATUT_EN_RETARD)
        self.stdout.write(self.style.SUCCESS(
            f"{count} maintenance(s) préventive(s) passée(s) en retard."
        ))
