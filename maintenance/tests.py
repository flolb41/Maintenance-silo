"""
Tests Django de l'application maintenance.
Couvre : rôles, accès inter-sites, workflows panne et préventive,
         retour obligatoire, uploads, factures, notifications, mark_overdue.
"""
import io
import os
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from maintenance.models import (
    Equipement,
    Facture,
    MaintenancePreventive,
    Notification,
    Panne,
    PanneMedia,
    PreventiveMedia,
    Profile,
    Site,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, role, sites=None):
    user = User.objects.create_user(username=username, password='testpass123')
    Profile.objects.create(user=user, role=role)
    if sites:
        for s in sites:
            s.utilisateurs.add(user)
    return user


def _png_file(name="test.png"):
    """Retourne un fichier PNG minimal valide en mémoire."""
    import struct
    import zlib

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    raw = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    data = signature + ihdr + idat + iend
    f = io.BytesIO(data)
    f.name = name
    return f


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), USE_SQLITE=True)
class SetupMixin(TestCase):
    def setUp(self):
        self.site1 = Site.objects.create(nom="Site Alpha", actif=True)
        self.site2 = Site.objects.create(nom="Site Beta", actif=True)
        self.eq1 = Equipement.objects.create(site=self.site1, nom="Conv A", actif=True)

        self.admin = make_user("admin_t", Profile.Role.ADMIN, [self.site1, self.site2])
        self.maintenance = make_user("maint_t", Profile.Role.MAINTENANCE, [self.site1])
        self.silo = make_user("silo_t", Profile.Role.SILO, [self.site1])
        self.silo2 = make_user("silo2_t", Profile.Role.SILO, [self.site2])  # autre site

        self.client = Client()


# ===========================================================================
# Tests d'authentification et de rôles
# ===========================================================================

class AuthTests(SetupMixin):
    def test_dashboard_redirect_si_non_authentifie(self):
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, "/auth/login/?next=/dashboard/")

    def test_login_ok(self):
        ok = self.client.login(username="admin_t", password='testpass123')
        self.assertTrue(ok)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)


# ===========================================================================
# Tests de la gestion des pannes
# ===========================================================================

class PanneWorkflowTests(SetupMixin):
    def _panne(self):
        return Panne.objects.create(
            site=self.site1,
            equipement=self.eq1,
            declarant=self.silo,
            titre="Panne test",
            description="Desc",
            priorite=Panne.Priorite.NORMALE,
            statut=Panne.Statut.NOUVELLE,
        )

    def test_creer_panne_silo(self):
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.post(
            reverse("panne_creer"),
            {
                "site": self.site1.pk,
                "equipement": self.eq1.pk,
                "titre": "Ma panne",
                "description": "Problème",
                "priorite": "normale",
            },
        )
        self.assertEqual(Panne.objects.filter(titre="Ma panne").count(), 1)

    def test_affecter_panne_maintenance(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        r = self.client.post(
            reverse("panne_affecter", args=[panne.pk]),
            {"agent_assigne": self.maintenance.pk},
        )
        panne.refresh_from_db()
        self.assertEqual(panne.statut, Panne.Statut.AFFECTEE)
        self.assertEqual(panne.agent_assigne, self.maintenance)

    def test_affecter_panne_silo_interdit(self):
        panne = self._panne()
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.post(
            reverse("panne_affecter", args=[panne.pk]),
            {"agent_assigne": self.maintenance.pk},
        )
        self.assertEqual(r.status_code, 403)

    def test_transition_invalide(self):
        panne = self._panne()  # statut = NOUVELLE
        self.client.login(username="maint_t", password='testpass123')
        # Transition NOUVELLE → RESOLUE est interdite
        r = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {"nouveau_statut": "resolue", "commentaire": ""},
        )
        panne.refresh_from_db()
        self.assertEqual(panne.statut, Panne.Statut.NOUVELLE)  # inchangé

    def test_acces_panne_autre_site_interdit(self):
        """silo2_t (site2) ne peut pas voir une panne du site1."""
        panne = self._panne()
        self.client.login(username="silo2_t", password='testpass123')
        r = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertEqual(r.status_code, 403)

    def test_acces_panne_autre_silo_interdit(self):
        """Un autre utilisateur silo du même site ne peut pas voir les pannes d'un autre silo."""
        silo_bis = make_user("silo_bis_t", Profile.Role.SILO, [self.site1])
        panne = self._panne()  # déclarant = silo_t
        self.client.login(username="silo_bis_t", password='testpass123')
        r = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertEqual(r.status_code, 403)


# ===========================================================================
# Tests du workflow des maintenances préventives
# ===========================================================================

class PreventiveWorkflowTests(SetupMixin):
    def _preventive(self, statut=MaintenancePreventive.Statut.ENVOYEE):
        return MaintenancePreventive.objects.create(
            site=self.site1,
            createur=self.maintenance,
            destinataire=self.silo,
            titre="Tâche test",
            instructions="Instructions",
            echeance=timezone.now() + timedelta(days=7),
            statut=statut,
        )

    def test_creer_preventive_maintenance(self):
        self.client.login(username="maint_t", password='testpass123')
        r = self.client.post(
            reverse("preventive_creer"),
            {
                "site": self.site1.pk,
                "destinataire": self.silo.pk,
                "titre": "Nouvelle tâche",
                "instructions": "Faire quelque chose",
                "echeance": "2030-01-01T10:00",
            },
        )
        self.assertEqual(
            MaintenancePreventive.objects.filter(titre="Nouvelle tâche").count(), 1
        )

    def test_silo_ne_peut_pas_creer(self):
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.get(reverse("preventive_creer"))
        self.assertEqual(r.status_code, 403)

    def test_silo_recoit_tache(self):
        p = self._preventive(MaintenancePreventive.Statut.ENVOYEE)
        self.client.login(username="silo_t", password='testpass123')
        self.client.post(reverse("preventive_recevoir", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.RECUE)

    def test_silo_demarre_tache(self):
        p = self._preventive(MaintenancePreventive.Statut.RECUE)
        self.client.login(username="silo_t", password='testpass123')
        self.client.post(reverse("preventive_demarrer", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.EN_COURS)

    def test_silo_termine_avec_retour(self):
        p = self._preventive(MaintenancePreventive.Statut.EN_COURS)
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.post(
            reverse("preventive_terminer", args=[p.pk]),
            {"retour": "Intervention réalisée correctement."},
        )
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.A_VALIDER)
        self.assertNotEqual(p.retour, "")

    def test_retour_obligatoire(self):
        p = self._preventive(MaintenancePreventive.Statut.EN_COURS)
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.post(
            reverse("preventive_terminer", args=[p.pk]),
            {"retour": ""},  # vide → erreur
        )
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.EN_COURS)  # inchangé

    def test_maintenance_valide(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        self.client.login(username="maint_t", password='testpass123')
        self.client.post(
            reverse("preventive_valider", args=[p.pk]),
            {"decision": "valider", "commentaire": ""},
        )
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.VALIDEE)

    def test_maintenance_rejette_avec_commentaire(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        self.client.login(username="maint_t", password='testpass123')
        self.client.post(
            reverse("preventive_valider", args=[p.pk]),
            {"decision": "rejeter", "commentaire": "Retour insuffisant."},
        )
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.REJETEE)

    def test_rejet_sans_commentaire_interdit(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        self.client.login(username="maint_t", password='testpass123')
        r = self.client.post(
            reverse("preventive_valider", args=[p.pk]),
            {"decision": "rejeter", "commentaire": ""},
        )
        p.refresh_from_db()
        self.assertNotEqual(p.statut, MaintenancePreventive.Statut.REJETEE)

    def test_silo_autre_site_ne_peut_pas_recevoir(self):
        p = self._preventive(MaintenancePreventive.Statut.ENVOYEE)
        self.client.login(username="silo2_t", password='testpass123')
        r = self.client.post(reverse("preventive_recevoir", args=[p.pk]))
        self.assertEqual(r.status_code, 404)
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.ENVOYEE)


# ===========================================================================
# Tests d'upload
# ===========================================================================

@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    MAX_UPLOAD_SIZE=100 * 1024,  # 100 Ko pour les tests
    ALLOWED_UPLOAD_EXTENSIONS=["jpg", "jpeg", "png", "pdf"],
)
class UploadTests(SetupMixin):
    def _panne(self):
        return Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Upload panne",
            description="Test",
            statut=Panne.Statut.NOUVELLE,
        )

    def test_upload_png_valide(self):
        panne = self._panne()
        self.client.login(username="silo_t", password='testpass123')
        f = _png_file("image.png")
        r = self.client.post(
            reverse("panne_ajouter_media", args=[panne.pk]),
            {"medias": f},
            format="multipart",
        )
        self.assertEqual(PanneMedia.objects.filter(panne=panne).count(), 1)

    def test_upload_extension_invalide(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        f = io.BytesIO(b"<?php echo 'hack'; ?>")
        f.name = "hack.php"
        r = self.client.post(
            reverse("panne_ajouter_media", args=[panne.pk]),
            {"medias": f},
            format="multipart",
        )
        self.assertEqual(PanneMedia.objects.filter(panne=panne).count(), 0)

    def test_upload_trop_volumineux(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        f = io.BytesIO(b"A" * (200 * 1024))  # 200 Ko > 100 Ko limite
        f.name = "gros.png"
        r = self.client.post(
            reverse("panne_ajouter_media", args=[panne.pk]),
            {"medias": f},
            format="multipart",
        )
        self.assertEqual(PanneMedia.objects.filter(panne=panne).count(), 0)

    def test_upload_acces_autre_site_interdit(self):
        panne = self._panne()
        self.client.login(username="silo2_t", password='testpass123')
        f = _png_file()
        r = self.client.post(
            reverse("panne_ajouter_media", args=[panne.pk]),
            {"medias": f},
            format="multipart",
        )
        # 404 = sécurité : l'objet n'est pas révélé aux utilisateurs d'autres sites
        self.assertIn(r.status_code, [403, 404])
        self.assertEqual(PanneMedia.objects.filter(panne=panne).count(), 0)


# ===========================================================================
# Tests des factures
# ===========================================================================

class FactureTests(SetupMixin):
    def _panne(self):
        return Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Panne facture",
            description="Test",
            statut=Panne.Statut.EN_COURS,
        )

    def test_ajouter_facture_coherente(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        r = self.client.post(
            reverse("panne_ajouter_facture", args=[panne.pk]),
            {
                "numero": "FAC-001",
                "fournisseur": "Fourni SA",
                "montant_ht": "100.00",
                "montant_ttc": "120.00",
            },
        )
        self.assertEqual(Facture.objects.filter(panne=panne).count(), 1)

    def test_facture_incoherente_ttc_inferieur_ht(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        r = self.client.post(
            reverse("panne_ajouter_facture", args=[panne.pk]),
            {
                "numero": "FAC-002",
                "fournisseur": "Fourni SA",
                "montant_ht": "200.00",
                "montant_ttc": "100.00",  # TTC < HT → invalide
            },
        )
        self.assertEqual(Facture.objects.filter(panne=panne).count(), 0)

    def test_silo_ne_peut_pas_ajouter_facture(self):
        panne = self._panne()
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.post(
            reverse("panne_ajouter_facture", args=[panne.pk]),
            {
                "numero": "FAC-003",
                "fournisseur": "X",
                "montant_ht": "50.00",
                "montant_ttc": "60.00",
            },
        )
        self.assertEqual(r.status_code, 403)


# ===========================================================================
# Tests des notifications
# ===========================================================================

class NotificationTests(SetupMixin):
    def test_notification_creee_a_la_creation_panne(self):
        """La création d'une panne génère des notifications pour admin/maintenance."""
        Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Notif test",
            description="Desc",
            statut=Panne.Statut.NOUVELLE,
        )
        self.assertTrue(
            Notification.objects.filter(
                utilisateur__in=[self.admin, self.maintenance],
                type_notif=Notification.TypeNotif.PANNE_CREEE,
            ).exists()
        )

    def test_notification_affectation(self):
        panne = Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Panne aff",
            description="",
            statut=Panne.Statut.NOUVELLE,
        )
        Notification.objects.all().delete()
        panne.agent_assigne = self.maintenance
        panne.statut = Panne.Statut.AFFECTEE
        panne.save()
        self.assertTrue(
            Notification.objects.filter(
                utilisateur=self.maintenance,
                type_notif=Notification.TypeNotif.PANNE_AFFECTEE,
            ).exists()
        )

    def test_marquer_notification_lue(self):
        notif = Notification.objects.create(
            utilisateur=self.silo,
            titre="Test",
            message="Msg",
            lue=False,
        )
        self.client.login(username="silo_t", password='testpass123')
        self.client.post(reverse("notification_marquer_lue", args=[notif.pk]))
        notif.refresh_from_db()
        self.assertTrue(notif.lue)

    def test_notification_autre_utilisateur_interdit(self):
        notif = Notification.objects.create(
            utilisateur=self.silo,
            titre="Test",
            message="Msg",
            lue=False,
        )
        self.client.login(username="silo2_t", password='testpass123')
        r = self.client.post(reverse("notification_marquer_lue", args=[notif.pk]))
        self.assertEqual(r.status_code, 404)


# ===========================================================================
# Tests de la commande mark_overdue
# ===========================================================================

class MarkOverdueTests(SetupMixin):
    def _expired_preventive(self, statut=MaintenancePreventive.Statut.ENVOYEE):
        return MaintenancePreventive.objects.create(
            site=self.site1,
            createur=self.maintenance,
            destinataire=self.silo,
            titre="Tâche expirée",
            instructions="...",
            echeance=timezone.now() - timedelta(days=3),
            statut=statut,
        )

    def test_mark_overdue_passe_en_retard(self):
        p = self._expired_preventive()
        call_command("mark_overdue", verbosity=0)
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.EN_RETARD)

    def test_mark_overdue_idempotent(self):
        p = self._expired_preventive()
        call_command("mark_overdue", verbosity=0)
        call_command("mark_overdue", verbosity=0)
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.EN_RETARD)
        # Pas de doublons de notification explosifs
        count = Notification.objects.filter(
            utilisateur=self.silo,
            type_notif=Notification.TypeNotif.PREVENTIVE_RETARD,
        ).count()
        self.assertEqual(count, 1)

    def test_mark_overdue_ne_touche_pas_validee(self):
        p = self._expired_preventive(MaintenancePreventive.Statut.VALIDEE)
        call_command("mark_overdue", verbosity=0)
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.VALIDEE)

    def test_mark_overdue_dry_run(self):
        p = self._expired_preventive()
        call_command("mark_overdue", "--dry-run", verbosity=0)
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.ENVOYEE)  # inchangé


# ===========================================================================
# Tests de la commande seed_demo
# ===========================================================================

class SeedDemoTests(SetupMixin):
    def test_seed_demo_cree_donnees(self):
        call_command("seed_demo", verbosity=0)
        self.assertTrue(Site.objects.filter(nom="Silo Nord").exists())
        self.assertTrue(User.objects.filter(username="admin_demo").exists())
