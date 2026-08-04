"""
Commande mark_overdue : passe en EN_RETARD les tâches préventives
dont l'échéance est dépassée et le statut non terminal.

Idempotente : peut être exécutée plusieurs fois sans effet de bord.
Recommandée en cron/systemd (ex. toutes les heures) ou Celery beat.

Exemple cron :
    0 * * * * /app/.venv/bin/python /app/manage.py mark_overdue

Exemple systemd timer :
    [Timer]
    OnCalendar=hourly
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from maintenance.models import MaintenancePreventive


STATUTS_TERMINAUX = {
    MaintenancePreventive.Statut.VALIDEE,
    MaintenancePreventive.Statut.EN_RETARD,
}


class Command(BaseCommand):
    help = "Passe en EN_RETARD les tâches préventives dont l'échéance est dépassée."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les tâches qui seraient marquées sans les modifier.",
        )

    def handle(self, *args, **options):
        maintenant = timezone.now()
        dry_run = options["dry_run"]

        taches = MaintenancePreventive.objects.filter(
            echeance__lt=maintenant,
        ).exclude(statut__in=STATUTS_TERMINAUX)

        count = taches.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("Aucune tâche en retard détectée."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f"[dry-run] {count} tâche(s) seraient marquées EN_RETARD :"))
            for t in taches:
                self.stdout.write(f"  #{t.pk} {t.titre} (échéance : {t.echeance})")
            return

        marquees = 0
        for tache in taches:
            ancien_statut = tache.statut
            tache.statut = MaintenancePreventive.Statut.EN_RETARD
            tache.save(update_fields=["statut", "modifiee_le"])
            marquees += 1

        self.stdout.write(
            self.style.SUCCESS(f"{marquees} tâche(s) passées en EN_RETARD.")
        )
