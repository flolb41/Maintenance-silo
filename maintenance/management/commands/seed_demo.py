from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from maintenance.models import (
    Site, Profile, Equipement, Panne, HistoriquePanne,
    MaintenancePreventive, Facture
)


class Command(BaseCommand):
    help = "Charge un jeu de données de démonstration."

    def handle(self, *args, **options):
        self.stdout.write("Création des données de démo...")

        # Sites
        s1, _ = Site.objects.get_or_create(
            nom="Silo de Beauce",
            defaults={"adresse": "28100 Dreux", "description": "Silo principal céréalier"}
        )
        s2, _ = Site.objects.get_or_create(
            nom="Silo de Brie",
            defaults={"adresse": "77120 Coulommiers", "description": "Silo secondaire"}
        )

        # Utilisateurs
        admin_user, created = User.objects.get_or_create(username='admin')
        if created:
            admin_user.set_password('admin123')
            admin_user.first_name = 'Admin'
            admin_user.last_name = 'Système'
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.save()
        profile_admin, _ = Profile.objects.get_or_create(user=admin_user)
        profile_admin.role = Profile.ROLE_ADMIN
        profile_admin.sites.set([s1, s2])
        profile_admin.save()

        maint_user, created = User.objects.get_or_create(username='technicien')
        if created:
            maint_user.set_password('tech123')
            maint_user.first_name = 'Jean'
            maint_user.last_name = 'Dupont'
            maint_user.save()
        profile_maint, _ = Profile.objects.get_or_create(user=maint_user)
        profile_maint.role = Profile.ROLE_MAINTENANCE
        profile_maint.sites.set([s1, s2])
        profile_maint.save()

        silo_user, created = User.objects.get_or_create(username='agent_silo')
        if created:
            silo_user.set_password('silo123')
            silo_user.first_name = 'Pierre'
            silo_user.last_name = 'Martin'
            silo_user.save()
        profile_silo, _ = Profile.objects.get_or_create(user=silo_user)
        profile_silo.role = Profile.ROLE_SILO
        profile_silo.sites.set([s1])
        profile_silo.save()

        # Équipements
        eq1, _ = Equipement.objects.get_or_create(
            site=s1, nom="Convoyeur principal",
            defaults={"categorie": "convoyeur", "reference": "CV-001", "date_installation": date(2018, 3, 15)}
        )
        eq2, _ = Equipement.objects.get_or_create(
            site=s1, nom="Élévateur à godets",
            defaults={"categorie": "elevateur", "reference": "EL-001", "date_installation": date(2019, 6, 1)}
        )
        eq3, _ = Equipement.objects.get_or_create(
            site=s2, nom="Ventilateur de séchage",
            defaults={"categorie": "ventilateur", "reference": "VT-001", "date_installation": date(2020, 1, 10)}
        )

        # Pannes
        if not Panne.objects.filter(titre="Moteur convoyeur en surchauffe").exists():
            p1 = Panne.objects.create(
                equipement=eq1,
                titre="Moteur convoyeur en surchauffe",
                description="Le moteur du convoyeur principal atteint des températures anormales.",
                priorite=Panne.PRIORITE_CRITIQUE,
                statut=Panne.STATUT_EN_COURS,
                signale_par=silo_user,
                affecte_a=maint_user,
                date_signalement=timezone.now() - timedelta(days=2),
            )
            HistoriquePanne.objects.create(
                panne=p1,
                ancien_statut=Panne.STATUT_NOUVELLE,
                nouveau_statut=Panne.STATUT_AFFECTEE,
                modifie_par=admin_user,
                commentaire='Affecté au technicien',
            )
            HistoriquePanne.objects.create(
                panne=p1,
                ancien_statut=Panne.STATUT_AFFECTEE,
                nouveau_statut=Panne.STATUT_EN_COURS,
                modifie_par=maint_user,
                commentaire='Intervention en cours',
            )

        if not Panne.objects.filter(titre="Capteur de niveau défaillant").exists():
            Panne.objects.create(
                equipement=eq2,
                titre="Capteur de niveau défaillant",
                description="Le capteur de niveau haute du silo 3 ne répond plus.",
                priorite=Panne.PRIORITE_HAUTE,
                statut=Panne.STATUT_NOUVELLE,
                signale_par=silo_user,
                date_signalement=timezone.now() - timedelta(hours=5),
            )

        if not Panne.objects.filter(titre="Fuite d'huile réducteur").exists():
            p3 = Panne.objects.create(
                equipement=eq3,
                titre="Fuite d'huile réducteur",
                description="Fuite d'huile constatée sur le réducteur de l'élévateur.",
                priorite=Panne.PRIORITE_NORMALE,
                statut=Panne.STATUT_RESOLUE,
                signale_par=maint_user,
                affecte_a=maint_user,
                date_signalement=timezone.now() - timedelta(days=10),
                date_resolution=timezone.now() - timedelta(days=8),
                solution='Remplacement du joint torique et appoint d\'huile.',
            )

        # Maintenances préventives
        if not MaintenancePreventive.objects.filter(titre="Graissage convoyeur principal").exists():
            MaintenancePreventive.objects.create(
                equipement=eq1,
                titre="Graissage convoyeur principal",
                description="Graissage complet de la chaîne et des paliers.",
                periodicite='mensuelle',
                date_echeance=date.today() + timedelta(days=5),
                statut=MaintenancePreventive.STATUT_PLANIFIEE,
                affecte_a=maint_user,
                created_by=admin_user,
            )

        if not MaintenancePreventive.objects.filter(titre="Révision annuelle élévateur").exists():
            MaintenancePreventive.objects.create(
                equipement=eq2,
                titre="Révision annuelle élévateur",
                description="Révision complète : courroies, godets, roulements.",
                periodicite='annuelle',
                date_echeance=date.today() - timedelta(days=3),
                statut=MaintenancePreventive.STATUT_EN_RETARD,
                affecte_a=maint_user,
                created_by=admin_user,
            )

        # Factures
        if not Facture.objects.filter(numero='FACT-2024-001').exists():
            p_resolue = Panne.objects.filter(titre="Fuite d'huile réducteur").first()
            if p_resolue:
                Facture.objects.create(
                    panne=p_resolue,
                    numero='FACT-2024-001',
                    fournisseur='Pièces Industrie SARL',
                    type_facture=Facture.TYPE_PIECES,
                    statut=Facture.STATUT_PAYEE,
                    montant_ht=Decimal('120.00'),
                    taux_tva=Decimal('20.00'),
                    montant_tva=Decimal('24.00'),
                    montant_ttc=Decimal('144.00'),
                    date_facture=date.today() - timedelta(days=7),
                    created_by=maint_user,
                )

        self.stdout.write(self.style.SUCCESS(
            "\nDonnées de démo créées avec succès !\n"
            "  admin / admin123    → Administrateur\n"
            "  technicien / tech123  → Équipe maintenance\n"
            "  agent_silo / silo123  → Agent silo\n"
        ))
