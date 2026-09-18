from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from maintenance.models import MaintenancePreventive


class Command(BaseCommand):
    help = "Génère les prochaines occurrences des préventives périodiques."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=31,
            help="Nombre de jours d'anticipation pour générer les tâches (défaut : 31).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les tâches à générer sans modifier la base.",
        )

    def handle(self, *args, **options):
        days_ahead = options["days_ahead"]
        if days_ahead < 0:
            raise CommandError("--days-ahead doit être positif ou nul.")

        maintenant = timezone.now()
        horizon = maintenant + timedelta(days=days_ahead)
        dry_run = options["dry_run"]
        racines = MaintenancePreventive.objects.filter(
            serie_parent__isnull=True,
            recurrence_active=True,
            periodicite__in=[
                MaintenancePreventive.Periodicite.MENSUELLE,
                MaintenancePreventive.Periodicite.TRIMESTRIELLE,
                MaintenancePreventive.Periodicite.ANNUELLE,
            ],
        ).values_list("pk", flat=True)

        generees = 0
        for racine_pk in racines.iterator():
            with transaction.atomic():
                racine = MaintenancePreventive.objects.select_for_update().get(
                    pk=racine_pk
                )
                derniere = racine.occurrences.order_by(
                    "-date_echeance").first()
                derniere_echeance = (
                    derniere.date_echeance if derniere else racine.date_echeance
                )
                prochaine = racine.prochaine_echeance_apres(derniere_echeance)

                while prochaine and prochaine < maintenant:
                    prochaine = racine.prochaine_echeance_apres(prochaine)

                while prochaine and prochaine <= horizon:
                    if (
                        racine.recurrence_jusquau
                        and prochaine.date() > racine.recurrence_jusquau
                    ):
                        if not dry_run:
                            racine.recurrence_active = False
                            racine.save(update_fields=[
                                        "recurrence_active", "updated_at"])
                        break

                    if dry_run:
                        self.stdout.write(
                            f"[dry-run] {racine.titre} : {prochaine.isoformat()}"
                        )
                        generees += 1
                    else:
                        _, created = MaintenancePreventive.objects.get_or_create(
                            serie_parent=racine,
                            date_echeance=prochaine,
                            defaults={
                                "site": racine.site,
                                "equipement": racine.equipement,
                                "created_by": racine.created_by,
                                "affecte_a": racine.affecte_a,
                                "titre": racine.titre,
                                "description": racine.description,
                                "statut": MaintenancePreventive.Statut.ENVOYEE,
                                "periodicite": racine.periodicite,
                                "recurrence_active": False,
                                "recurrence_jusquau": racine.recurrence_jusquau,
                            },
                        )
                        generees += int(created)
                    prochaine = racine.prochaine_echeance_apres(prochaine)

        prefixe = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefixe}{generees} occurrence(s) préventive(s) générée(s)."
            )
        )
