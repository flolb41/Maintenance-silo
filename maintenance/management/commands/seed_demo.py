"""
Commande seed_demo : peuple la base de données avec des données de démonstration.

Usage :
    python manage.py seed_demo [--reset]

Les mots de passe de démonstration sont volontairement faibles et ne doivent
JAMAIS être utilisés en production.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from maintenance.models import (
    Equipement,
    MaintenancePreventive,
    Panne,
    Profile,
    Site,
)

User = get_user_model()

DEMO_USERS = [
    {"username": "admin_demo", "password": "demo1234!", "role": Profile.Role.ADMIN, "first_name": "Alice", "last_name": "Admin"},
    {"username": "maintenance_demo", "password": "demo1234!", "role": Profile.Role.MAINTENANCE, "first_name": "Marc", "last_name": "Maintenance"},
    {"username": "silo_demo", "password": "demo1234!", "role": Profile.Role.SILO, "first_name": "Sam", "last_name": "Silo"},
    {"username": "silo2_demo", "password": "demo1234!", "role": Profile.Role.SILO, "first_name": "Sophie", "last_name": "Silo2"},
]


class Command(BaseCommand):
    help = "Peuple la base avec des données de démonstration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime les données existantes avant d'insérer.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self.stdout.write(self.style.WARNING("Suppression des données existantes…"))
            MaintenancePreventive.objects.all().delete()
            Panne.objects.all().delete()
            Equipement.objects.all().delete()
            Site.objects.all().delete()
            User.objects.filter(username__endswith="_demo").delete()

        # Création des sites
        site1, _ = Site.objects.get_or_create(nom="Silo Nord", defaults={"adresse": "Zone industrielle Nord", "actif": True})
        site2, _ = Site.objects.get_or_create(nom="Silo Sud", defaults={"adresse": "Zone industrielle Sud", "actif": True})

        # Création des équipements
        eq1, _ = Equipement.objects.get_or_create(site=site1, nom="Convoyeur A", defaults={"reference": "CA-001"})
        eq2, _ = Equipement.objects.get_or_create(site=site1, nom="Élévateur B", defaults={"reference": "EB-002"})
        eq3, _ = Equipement.objects.get_or_create(site=site2, nom="Trémie C", defaults={"reference": "TC-003"})

        # Création des utilisateurs
        users = {}
        for u_data in DEMO_USERS:
            u, created = User.objects.get_or_create(
                username=u_data["username"],
                defaults={
                    "first_name": u_data["first_name"],
                    "last_name": u_data["last_name"],
                    "is_staff": u_data["role"] == Profile.Role.ADMIN,
                    "is_superuser": u_data["role"] == Profile.Role.ADMIN,
                },
            )
            if created:
                u.set_password(u_data["password"])
                u.save()
            Profile.objects.get_or_create(user=u, defaults={"role": u_data["role"]})
            users[u_data["username"]] = u

        # Association sites/utilisateurs
        site1.utilisateurs.add(users["admin_demo"], users["maintenance_demo"], users["silo_demo"])
        site2.utilisateurs.add(users["admin_demo"], users["silo2_demo"])

        # Création de pannes
        panne1, _ = Panne.objects.get_or_create(
            titre="Convoyeur A – arrêt total",
            defaults={
                "site": site1,
                "equipement": eq1,
                "declarant": users["silo_demo"],
                "priorite": Panne.Priorite.CRITIQUE,
                "statut": Panne.Statut.NOUVELLE,
                "description": "Le convoyeur A ne démarre plus depuis ce matin.",
            },
        )

        panne2, _ = Panne.objects.get_or_create(
            titre="Élévateur B – bruit anormal",
            defaults={
                "site": site1,
                "equipement": eq2,
                "declarant": users["silo_demo"],
                "agent_assigne": users["maintenance_demo"],
                "priorite": Panne.Priorite.HAUTE,
                "statut": Panne.Statut.EN_COURS,
                "description": "L'élévateur B produit un bruit anormal à pleine charge.",
            },
        )

        # Création de tâches préventives
        now = timezone.now()
        MaintenancePreventive.objects.get_or_create(
            titre="Vérification mensuelle convoyeur A",
            defaults={
                "site": site1,
                "equipement": eq1,
                "createur": users["maintenance_demo"],
                "destinataire": users["silo_demo"],
                "instructions": "1. Vérifier les courroies\n2. Lubrifier les roulements\n3. Contrôler les boulons",
                "echeance": now + timezone.timedelta(days=7),
                "statut": MaintenancePreventive.Statut.ENVOYEE,
            },
        )

        MaintenancePreventive.objects.get_or_create(
            titre="Inspection trimestrielle trémie C",
            defaults={
                "site": site2,
                "equipement": eq3,
                "createur": users["admin_demo"],
                "destinataire": users["silo2_demo"],
                "instructions": "Vérifier l'état de la grille et le moteur de vibration.",
                "echeance": now - timezone.timedelta(days=2),
                "statut": MaintenancePreventive.Statut.EN_RETARD,
            },
        )

        self.stdout.write(self.style.SUCCESS("Données de démonstration créées avec succès."))
        self.stdout.write("")
        self.stdout.write("Comptes de démonstration (NE PAS UTILISER EN PRODUCTION) :")
        for u_data in DEMO_USERS:
            self.stdout.write(f"  {u_data['username']} / {u_data['password']}  ({u_data['role']})")
