"""
Tests Django de l'application maintenance.
Couvre : rôles, accès inter-sites, workflows panne et préventive,
         retour obligatoire, uploads, factures, notifications, mark_overdue.
"""
import io
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from maintenance.mixins import get_sites_utilisateur
from maintenance.facture_extraction import extract_invoice_data_from_document
from maintenance.forms import FactureForm
from maintenance.models import (
    CelluleGrain,
    Equipement,
    Facture,
    HistoriquePreventive,
    MaintenancePreventive,
    PieceDetachee,
    PiecePanne,
    Notification,
    Panne,
    PanneMedia,
    PanneTempsIntervention,
    PreventiveMedia,
    Profile,
    ReleveCellule,
    ReleveStockageAPlat,
    Silo,
    Site,
    SitePhoto,
    StockageAPlat,
    TypeGrain,
)
from vehicules.models import Vehicule

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
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + \
        struct.pack(">I", ihdr_crc)

    raw = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + \
        compressed + struct.pack(">I", idat_crc)

    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    data = signature + ihdr + idat + iend
    f = io.BytesIO(data)
    f.name = name
    return f


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PRIVATE_INVOICE_ROOT=tempfile.mkdtemp(),
    USE_SQLITE=True,
)
class SetupMixin(TestCase):
    def setUp(self):
        self.site1 = Site.objects.create(nom="Site Alpha", actif=True)
        self.site2 = Site.objects.create(nom="Site Beta", actif=True)
        self.eq1 = Equipement.objects.create(
            site=self.site1, nom="Conv A", actif=True)

        self.admin = make_user("admin_t", Profile.Role.ADMIN, [
                               self.site1, self.site2])
        self.maintenance = make_user(
            "maint_t", Profile.Role.MAINTENANCE, [self.site1])
        self.silo = make_user("silo_t", Profile.Role.SILO, [self.site1])
        self.silo2 = make_user("silo2_t", Profile.Role.SILO, [
                               self.site2])  # autre site

        self.client = Client()


class PiecePanneTests(SetupMixin):
    def test_reservation_consommation_et_restitution_piece(self):
        panne = Panne.objects.create(site=self.site1, signale_par=self.silo, affecte_a=self.maintenance,
                                     titre="Panne avec pièce", description="Test", statut=Panne.STATUT_EN_COURS)
        piece = PieceDetachee.objects.create(
            site=self.site1, reference="TEST-001", nom="Pièce de test", stock=3, seuil_alerte=1)
        self.client.login(username="maint_t", password="testpass123")
        response = self.client.post(reverse("panne_reserver_piece", args=[panne.pk]), {
                                    "piece": piece.pk, "quantite": 2, "commentaire": "Réparation"}, secure=True)
        self.assertEqual(response.status_code, 302)
        piece.refresh_from_db()
        self.assertEqual(piece.stock, 1)
        reservation = PiecePanne.objects.get(panne=panne)
        response = self.client.post(reverse("panne_consomer_piece", args=[
                                    panne.pk, reservation.pk]), secure=True)
        self.assertEqual(response.status_code, 302)
        piece.refresh_from_db()
        self.assertEqual(piece.stock, 1)
        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, PiecePanne.Statut.CONSOMMEE)


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

    def test_dashboard_cree_profil_si_absent_pour_utilisateur_authentifie(self):
        user = User.objects.create_user(
            username="silo_sans_profil", password='testpass123')
        self.client.login(username="silo_sans_profil", password='testpass123')

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Profile.objects.filter(user=user).exists())

    def test_agents_ne_peuvent_pas_modifier_leur_role_depuis_mon_profil(self):
        for username, profile in (
            ("maint_t", self.maintenance.profile),
            ("silo_t", self.silo.profile),
        ):
            role_initial = profile.role
            with self.subTest(username=username):
                self.client.login(username=username, password='testpass123')
                detail = self.client.get(reverse("mon_profil"))
                self.assertEqual(detail.status_code, 200)
                self.assertNotContains(detail, 'name="role"')
                self.assertContains(detail, profile.get_role_display())

                response = self.client.post(reverse("mon_profil"), {
                    "first_name": "Prénom modifié",
                    "last_name": "Nom modifié",
                    "role": Profile.Role.ADMIN,
                })
                self.assertRedirects(response, reverse("mon_profil"))
                profile.refresh_from_db()
                self.assertEqual(profile.role, role_initial)
                profile.user.refresh_from_db()
                self.assertEqual(profile.user.first_name, "Prénom modifié")
                self.assertEqual(profile.user.last_name, "Nom modifié")

    def test_utilisateur_modifie_son_mot_de_passe(self):
        self.client.login(username="silo_t", password="testpass123")

        response = self.client.post(reverse("password_change"), {
            "old_password": "testpass123",
            "new_password1": "Nouveau-mot-de-passe-2026!",
            "new_password2": "Nouveau-mot-de-passe-2026!",
        })

        self.assertRedirects(response, reverse("password_change_done"))
        self.silo.refresh_from_db()
        self.assertTrue(self.silo.check_password("Nouveau-mot-de-passe-2026!"))
        self.assertEqual(self.client.get(
            reverse("dashboard")).status_code, 200)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_recuperation_mot_de_passe_par_email_du_profil(self):
        self.silo.email = "silo.recuperation@example.com"
        self.silo.save(update_fields=["email"])
        reset_form = PasswordResetForm({
            "email": "silo.recuperation@example.com",
        })
        self.assertTrue(reset_form.is_valid())
        self.assertEqual(
            list(reset_form.get_users("silo.recuperation@example.com")),
            [self.silo],
        )

        response = self.client.post(reverse("password_reset"), {
            "email": "silo.recuperation@example.com",
        })

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("silo.recuperation@example.com", mail.outbox[0].to)
        self.assertIn("/auth/reinitialisation/", mail.outbox[0].body)


# ===========================================================================
# Tests de la gestion des pannes
# ===========================================================================

class GestionSilosTests(SetupMixin):
    def setUp(self):
        super().setUp()
        self.ble = TypeGrain.objects.create(
            nom="Blé tendre",
            poids_specifique_moyen=Decimal("75.00"),
        )
        self.cellule = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule 1",
            type_grain=self.ble,
            forme=CelluleGrain.Forme.CARREE,
            longueur_m=Decimal("10.00"),
            hauteur_m=Decimal("10.00"),
        )
        self.cellule_autre_site = CelluleGrain.objects.create(
            site=self.site2,
            nom="Cellule B1",
            type_grain=self.ble,
            forme=CelluleGrain.Forme.RECTANGULAIRE,
            longueur_m=Decimal("10.00"),
            largeur_m=Decimal("8.00"),
            hauteur_m=Decimal("10.00"),
        )

    def test_dashboard_admin_resume_stocks_pannes_et_vehicules(self):
        ReleveCellule.objects.create(
            cellule=self.cellule,
            type_grain=self.ble,
            tonnage_manuel=Decimal("500.00"),
            releve_par=self.silo,
        )
        panne_a_affecter = Panne.objects.create(
            site=self.site1,
            signale_par=self.silo,
            titre="Convoyeur arrêté",
            description="Arrêt complet",
            statut=Panne.STATUT_NOUVELLE,
        )
        Panne.objects.create(
            site=self.site1,
            signale_par=self.silo,
            affecte_a=self.maintenance,
            titre="Panne déjà affectée",
            description="En cours de traitement",
            statut=Panne.STATUT_AFFECTEE,
        )
        Vehicule.objects.create(
            site=self.site1,
            categorie=Vehicule.Categorie.POIDS_LOURD,
            immatriculation="AA-123-AA",
            marque="Renault Trucks",
            modele="T",
            statut=Vehicule.Statut.EN_ENTRETIEN,
            cree_par=self.admin,
        )

        self.client.login(username="admin_t", password="testpass123")
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion de silos Agri Négoce")
        self.assertEqual(
            list(response.context["pannes_a_affecter_recentes"]),
            [panne_a_affecter],
        )
        self.assertEqual(
            response.context["stock_total_tonnes"], Decimal("500.00"))
        self.assertEqual(
            response.context["stocks_par_grain"][0]["grain"], "Blé tendre")
        self.assertEqual(
            response.context["stocks_par_grain"][0]["stock"], Decimal("500.00"))
        self.assertEqual(len(response.context["stocks_par_site"]), 2)
        self.assertEqual(response.context["vehicules_actifs"], 1)
        self.assertEqual(response.context["vehicules_indisponibles"], 1)

    def test_dashboard_admin_applique_les_filtres_analytiques(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.get(reverse("dashboard"), {
            "analytics_site": self.site1.pk,
            "analytics_start": "2026-01-01",
            "analytics_end": "2026-12-31",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["analytics_filters"]["site"], str(self.site1.pk))
        self.assertEqual(
            response.context["analytics_filters"]["start"], "2026-01-01")
        self.assertEqual(
            response.context["analytics_filters"]["end"], "2026-12-31")

    def test_dashboard_admin_detaille_les_grains_par_site(self):
        ReleveCellule.objects.create(
            cellule=self.cellule,
            type_grain=self.ble,
            tonnage_manuel=Decimal("500.00"),
            releve_par=self.silo,
        )
        ReleveCellule.objects.create(
            cellule=self.cellule_autre_site,
            type_grain=self.ble,
            tonnage_manuel=Decimal("250.00"),
            releve_par=self.silo,
        )
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        site = next(
            ligne for ligne in response.context["stocks_par_site"]
            if ligne["id"] == self.site1.pk
        )
        self.assertEqual(len(site["grains"]), 1)
        self.assertEqual(site["grains"][0]["grain"], "Blé tendre")
        self.assertEqual(site["grains"][0]["stock"], Decimal("500.00"))
        self.assertContains(
            response,
            f'data-bs-target="#site-grains-{self.site1.pk}"',
        )
        self.assertContains(response, f'id="site-grains-{self.site1.pk}"')
        grain = response.context["stocks_par_grain"][0]
        self.assertEqual(
            {site["site"]: site["stock"] for site in grain["sites"]},
            {self.site1.nom: Decimal(
                "500.00"), self.site2.nom: Decimal("250.00")},
        )
        self.assertContains(
            response,
            f'data-bs-target="#grain-sites-{self.ble.pk}"',
        )
        self.assertContains(response, f'id="grain-sites-{self.ble.pk}"')
        self.assertContains(response, "Tonnage par site · Blé tendre")

    def test_cellules_vides_et_en_maintenance_ne_sont_pas_des_stocks_incomplets(self):
        cellule_vide = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule vide",
            etat=CelluleGrain.Etat.VIDE,
            forme=CelluleGrain.Forme.CARREE,
            longueur_m=Decimal("8.00"),
            hauteur_m=Decimal("10.00"),
        )
        cellule_nettoyage = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule en nettoyage",
            etat=CelluleGrain.Etat.NETTOYAGE,
            forme=CelluleGrain.Forme.CARREE,
            longueur_m=Decimal("8.00"),
            hauteur_m=Decimal("10.00"),
        )
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["cellules_vides"], 1)
        self.assertEqual(response.context["cellules_maintenance"], 1)
        self.assertEqual(response.context["cellules_sans_releve"], 2)
        self.assertNotContains(response, "Non configuré")
        self.assertContains(response, "1 vide")
        self.assertContains(response, "1 en maintenance")

        self.client.login(username="silo_t", password="testpass123")
        for cellule in (cellule_vide, cellule_nettoyage):
            with self.subTest(etat=cellule.etat):
                saisie = self.client.get(
                    reverse("cellule_grain_relever", args=[cellule.pk])
                )
                self.assertRedirects(
                    saisie,
                    reverse("cellule_grain_detail", args=[cellule.pk]),
                )

    def test_admin_configure_cellule_et_type_grain(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("cellule_grain_create"), {
            "silo": self.cellule.silo_id,
            "nom": "Cellule 2",
            "type_grain": self.ble.pk,
            "forme": CelluleGrain.Forme.RONDE,
            "diametre_m": "10.00",
            "hauteur_m": "10.00",
            "actif": "on",
        })

        self.assertRedirects(response, reverse("gestion_silos"))
        cellule = CelluleGrain.objects.get(nom="Cellule 2")
        self.assertEqual(
            cellule.capacite_m3.quantize(Decimal("0.01")),
            Decimal("811.58"),
        )
        self.assertEqual(cellule.capacite_tonnes, Decimal("608.69"))

        response = self.client.post(reverse("type_grain_create"), {
            "nom": "Orge",
            "poids_specifique_moyen": "65.50",
            "actif": "on",
        })
        self.assertRedirects(response, reverse("gestion_silos"))
        self.assertTrue(TypeGrain.objects.filter(nom="Orge").exists())

    def test_admin_configure_un_stockage_a_plat(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("stockage_a_plat_create"), {
            "site": self.site1.pk,
            "nom": "Hangar moisson",
            "type_grain": self.ble.pk,
            "actif": "on",
        })

        self.assertRedirects(response, reverse("gestion_silos"))
        stockage = StockageAPlat.objects.get(nom="Hangar moisson")
        self.assertEqual(stockage.site, self.site1)
        self.assertEqual(stockage.type_grain, self.ble)

    def test_silo_voit_et_cree_un_stockage_a_plat_sur_son_site(self):
        self.client.login(username="silo_t", password="testpass123")

        liste = self.client.get(reverse("gestion_silos"))

        self.assertContains(liste, "Ajouter un stockage à plat")
        self.assertContains(liste, "Créer le premier stockage à plat")

        formulaire = self.client.get(reverse("stockage_a_plat_create"))
        self.assertEqual(formulaire.status_code, 200)
        self.assertContains(formulaire, self.site1.nom)
        self.assertNotContains(formulaire, self.site2.nom)

        response = self.client.post(reverse("stockage_a_plat_create"), {
            "site": self.site1.pk,
            "nom": "Hangar temporaire",
            "type_grain": self.ble.pk,
            "actif": "on",
        })

        self.assertRedirects(response, reverse("gestion_silos"))
        self.assertTrue(StockageAPlat.objects.filter(
            site=self.site1,
            nom="Hangar temporaire",
        ).exists())

    def test_silo_saisit_le_tonnage_du_stockage_a_plat_de_son_site(self):
        stockage = StockageAPlat.objects.create(
            site=self.site1,
            nom="Hangar moisson",
            type_grain=self.ble,
        )
        stockage_autre_site = StockageAPlat.objects.create(
            site=self.site2,
            nom="Bâtiment annexe",
            type_grain=self.ble,
        )
        self.client.login(username="silo_t", password="testpass123")

        response = self.client.post(
            reverse("stockage_a_plat_relever", args=[stockage.pk]),
            {
                "type_grain": self.ble.pk,
                "tonnage": "325.50",
                "releve_le": "2026-09-05T10:30",
                "commentaire": "Stock exceptionnel",
            },
        )

        self.assertRedirects(
            response,
            reverse("stockage_a_plat_detail", args=[stockage.pk]),
        )
        releve = ReleveStockageAPlat.objects.get(stockage=stockage)
        self.assertEqual(releve.type_grain, self.ble)
        self.assertEqual(releve.tonnage, Decimal("325.50"))
        self.assertEqual(releve.releve_par, self.silo)
        self.assertEqual(
            self.client.get(reverse(
                "stockage_a_plat_relever", args=[stockage_autre_site.pk]
            )).status_code,
            404,
        )

    def test_dashboard_ajoute_uniquement_le_dernier_tonnage_a_plat(self):
        stockage = StockageAPlat.objects.create(
            site=self.site1,
            nom="Hangar moisson",
            type_grain=self.ble,
        )
        ReleveStockageAPlat.objects.create(
            stockage=stockage,
            tonnage=Decimal("100.00"),
            releve_le=timezone.make_aware(datetime(2026, 9, 4, 10, 0)),
            releve_par=self.silo,
        )
        ReleveStockageAPlat.objects.create(
            stockage=stockage,
            tonnage=Decimal("125.00"),
            releve_le=timezone.make_aware(datetime(2026, 9, 5, 10, 0)),
            releve_par=self.silo,
        )
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(
            response.context["stock_total_tonnes"], Decimal("125.00"))
        self.assertEqual(
            response.context["stocks_par_grain"][0]["stock_a_plat"],
            Decimal("125.00"),
        )
        self.assertContains(response, "dont 125,0 t à plat")

    def test_stockage_a_plat_conserve_plusieurs_grains(self):
        orge = TypeGrain.objects.create(
            nom="Orge",
            poids_specifique_moyen=Decimal("65.00"),
        )
        stockage = StockageAPlat.objects.create(
            site=self.site1,
            nom="Hangar moisson",
            type_grain=self.ble,
        )
        ReleveStockageAPlat.objects.create(
            stockage=stockage,
            type_grain=self.ble,
            tonnage=Decimal("100.00"),
            releve_le=timezone.make_aware(datetime(2026, 9, 4, 10, 0)),
            releve_par=self.silo,
        )
        ReleveStockageAPlat.objects.create(
            stockage=stockage,
            type_grain=orge,
            tonnage=Decimal("125.00"),
            releve_le=timezone.make_aware(datetime(2026, 9, 5, 10, 0)),
            releve_par=self.silo,
        )
        self.client.login(username="admin_t", password="testpass123")

        dashboard = self.client.get(reverse("dashboard"))
        gestion_silos = self.client.get(reverse("gestion_silos"))

        self.assertEqual(
            dashboard.context["stock_total_tonnes"], Decimal("225.00"))
        self.assertEqual(
            {ligne["grain"]
                for ligne in dashboard.context["stocks_par_grain"]},
            {"Blé tendre", "Orge"},
        )
        self.assertContains(gestion_silos, "Blé tendre")
        self.assertContains(gestion_silos, "Orge")

    def test_modification_poids_specifique_recalcule_capacite_cellules(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(
            reverse("type_grain_update", args=[self.ble.pk]),
            {
                "nom": self.ble.nom,
                "poids_specifique_moyen": "80.00",
                "actif": "on",
            },
        )

        self.assertRedirects(response, reverse("gestion_silos"))
        self.cellule.refresh_from_db()
        self.assertEqual(self.cellule.capacite_tonnes, Decimal("826.66"))

    def test_cellule_prive_16x20_a_une_capacite_maximale_de_2700_tonnes(self):
        cellule_prive = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule Privé 16x20",
            marque="Privé",
            type_grain=self.ble,
            forme=CelluleGrain.Forme.RONDE,
            diametre_m=Decimal("16.00"),
            hauteur_m=Decimal("20.00"),
        )
        cellule_autre_marque = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule standard 16x20",
            marque="Autre",
            type_grain=self.ble,
            forme=CelluleGrain.Forme.RONDE,
            diametre_m=Decimal("16.00"),
            hauteur_m=Decimal("20.00"),
        )

        self.assertEqual(cellule_prive.capacite_tonnes, Decimal("2700.00"))
        self.assertNotEqual(
            cellule_autre_marque.capacite_tonnes,
            Decimal("2700.00"),
        )

        releve = ReleveCellule.objects.create(
            cellule=cellule_prive,
            type_grain=self.ble,
            tonnage_manuel=Decimal("2700.00"),
            releve_par=self.silo,
        )
        self.assertEqual(releve.taux_remplissage, Decimal("100"))

    def test_cellule_sans_grain_ne_peut_pas_recevoir_de_stock(self):
        cellule = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule à configurer",
            forme=CelluleGrain.Forme.CARREE,
            longueur_m=Decimal("10.00"),
            hauteur_m=Decimal("10.00"),
        )
        self.client.login(username="silo_t", password="testpass123")

        liste = self.client.get(reverse("gestion_silos"))
        response = self.client.get(
            reverse("cellule_grain_relever", args=[cellule.pk])
        )

        self.assertContains(liste, "Grain à configurer")
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("cellule_grain_detail", args=[cellule.pk]),
        )

    def test_filtre_les_cellules_par_type_de_cereale(self):
        orge = TypeGrain.objects.create(
            nom="Orge",
            poids_specifique_moyen=Decimal("65.00"),
        )
        cellule_orge = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule orge",
            type_grain=orge,
            forme=CelluleGrain.Forme.CARREE,
            longueur_m=Decimal("10.00"),
            hauteur_m=Decimal("10.00"),
        )
        self.client.login(username="silo_t", password="testpass123")

        response = self.client.get(
            reverse("gestion_silos"),
            {"type_grain": self.ble.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Type de céréale")
        self.assertContains(response, self.cellule.nom)
        self.assertNotContains(response, cellule_orge.nom)

    def test_admin_cree_un_site_avec_plusieurs_cellules_dimensionnees(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("site_create"), {
            "nom": "Site géométrique",
            "adresse": "Zone céréales",
            "actif": "on",
            "cellules-TOTAL_FORMS": "2",
            "cellules-INITIAL_FORMS": "0",
            "cellules-MIN_NUM_FORMS": "0",
            "cellules-MAX_NUM_FORMS": "1000",
            "cellules-0-nom": "Ronde 1",
            "cellules-0-type_grain": self.ble.pk,
            "cellules-0-forme": CelluleGrain.Forme.RONDE,
            "cellules-0-hauteur_m": "12.00",
            "cellules-0-diametre_m": "8.00",
            "cellules-0-actif": "on",
            "cellules-1-nom": "Rectangle 1",
            "cellules-1-type_grain": self.ble.pk,
            "cellules-1-forme": CelluleGrain.Forme.RECTANGULAIRE,
            "cellules-1-hauteur_m": "10.00",
            "cellules-1-longueur_m": "12.00",
            "cellules-1-largeur_m": "6.00",
            "cellules-1-actif": "on",
        })

        self.assertRedirects(
            response,
            reverse("site_list"),
            fetch_redirect_response=False,
        )
        site = Site.objects.get(nom="Site géométrique")
        self.assertEqual(site.cellules_grain.count(), 2)
        rectangle = site.cellules_grain.get(nom="Rectangle 1")
        self.assertEqual(rectangle.capacite_m3, Decimal("744.00"))

    def test_admin_cree_un_site_depuis_le_formulaire_actuel_sans_silo(self):
        self.client.login(username="admin_t", password="testpass123")
        donnees = {
            "nom": "Nouveau site sans silo",
            "adresse": "Adresse test",
            "actif": "on",
            "silos-TOTAL_FORMS": "5",
            "silos-INITIAL_FORMS": "0",
            "silos-MIN_NUM_FORMS": "0",
            "silos-MAX_NUM_FORMS": "1000",
        }
        for index in range(5):
            donnees.update({
                f"silos-{index}-nom": "",
                f"silos-{index}-description": "",
                f"silos-{index}-cellules-TOTAL_FORMS": "1",
                f"silos-{index}-cellules-INITIAL_FORMS": "0",
                f"silos-{index}-cellules-MIN_NUM_FORMS": "0",
                f"silos-{index}-cellules-MAX_NUM_FORMS": "1000",
                f"silos-{index}-cellules-0-forme": CelluleGrain.Forme.RONDE,
            })

        response = self.client.post(reverse("site_create"), donnees)

        self.assertRedirects(response, reverse("site_list"))
        site = Site.objects.get(nom="Nouveau site sans silo")
        self.assertEqual(site.silos.count(), 0)

    def test_site_ignore_les_cellules_vides_preaffichees(self):
        self.client.login(username="admin_t", password="testpass123")
        donnees = {
            "nom": "Site sans structure",
            "adresse": "Adresse test",
            "actif": "on",
            "silos-TOTAL_FORMS": "5",
            "silos-INITIAL_FORMS": "0",
            "silos-MIN_NUM_FORMS": "0",
            "silos-MAX_NUM_FORMS": "1000",
        }
        for index in range(5):
            prefix = f"silos-{index}-cellules"
            donnees.update({
                f"silos-{index}-nom": "",
                f"silos-{index}-description": "",
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
                f"{prefix}-0-nom": "",
                f"{prefix}-0-marque": "",
                f"{prefix}-0-etat": CelluleGrain.Etat.EN_SERVICE,
                f"{prefix}-0-forme": CelluleGrain.Forme.RONDE,
                f"{prefix}-0-hauteur_m": "",
                f"{prefix}-0-diametre_m": "",
                f"{prefix}-0-longueur_m": "",
                f"{prefix}-0-largeur_m": "",
                f"{prefix}-0-nombre_toles_hauteur": "15",
            })

        response = self.client.post(
            reverse("site_create"),
            donnees,
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("site_list"),
            fetch_redirect_response=False,
        )
        site = Site.objects.get(nom="Site sans structure")
        self.assertEqual(site.silos.count(), 0)

    def test_admin_modifie_un_site_sans_silo_depuis_le_formulaire_actuel(self):
        self.client.login(username="admin_t", password="testpass123")
        site = Site.objects.create(nom="Site sans silo", actif=True)
        donnees = {
            "nom": "Site sans silo modifié",
            "adresse": "Adresse modifiée",
            "actif": "on",
            "silos-TOTAL_FORMS": "5",
            "silos-INITIAL_FORMS": "0",
            "silos-MIN_NUM_FORMS": "0",
            "silos-MAX_NUM_FORMS": "1000",
        }
        for index in range(5):
            donnees.update({
                f"silos-{index}-nom": "",
                f"silos-{index}-description": "",
                f"silos-{index}-cellules-TOTAL_FORMS": "1",
                f"silos-{index}-cellules-INITIAL_FORMS": "0",
                f"silos-{index}-cellules-MIN_NUM_FORMS": "0",
                f"silos-{index}-cellules-MAX_NUM_FORMS": "1000",
                f"silos-{index}-cellules-0-forme": CelluleGrain.Forme.RONDE,
            })

        response = self.client.post(
            reverse("site_update", args=[site.pk]),
            donnees,
        )

        self.assertRedirects(response, reverse("site_list"))
        site.refresh_from_db()
        self.assertEqual(site.nom, "Site sans silo modifié")
        self.assertEqual(site.silos.count(), 0)

    def test_admin_modifie_un_site_et_ajoute_une_cellule(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("site_update", args=[self.site1.pk]), {
            "nom": "Site Alpha modifié",
            "adresse": "Nouvelle adresse",
            "actif": "on",
            "cellules-TOTAL_FORMS": "2",
            "cellules-INITIAL_FORMS": "1",
            "cellules-MIN_NUM_FORMS": "0",
            "cellules-MAX_NUM_FORMS": "1000",
            "cellules-0-id": self.cellule.pk,
            "cellules-0-nom": self.cellule.nom,
            "cellules-0-type_grain": self.ble.pk,
            "cellules-0-forme": self.cellule.forme,
            "cellules-0-hauteur_m": str(self.cellule.hauteur_m),
            "cellules-0-longueur_m": str(self.cellule.longueur_m),
            "cellules-0-actif": "on",
            "cellules-1-nom": "Cellule 2",
            "cellules-1-type_grain": self.ble.pk,
            "cellules-1-forme": CelluleGrain.Forme.RONDE,
            "cellules-1-hauteur_m": "12.00",
            "cellules-1-diametre_m": "8.00",
            "cellules-1-actif": "on",
        })

        self.assertRedirects(response, reverse("site_list"))
        self.site1.refresh_from_db()
        self.assertEqual(self.site1.nom, "Site Alpha modifié")
        self.assertEqual(self.site1.cellules_grain.count(), 2)

    def test_admin_structure_un_site_en_plusieurs_silos(self):
        self.client.login(username="admin_t", password="testpass123")
        silo_principal = self.cellule.silo

        page = self.client.get(reverse("site_update", args=[self.site1.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Silos et cellules")
        self.assertContains(page, silo_principal.nom)
        self.assertContains(page, self.cellule.nom)

        response = self.client.post(reverse("site_update", args=[self.site1.pk]), {
            "nom": "Herbault Centre",
            "adresse": "Zone de stockage",
            "actif": "on",
            "silos-TOTAL_FORMS": "2",
            "silos-INITIAL_FORMS": "1",
            "silos-MIN_NUM_FORMS": "0",
            "silos-MAX_NUM_FORMS": "1000",
            "silos-0-id": silo_principal.pk,
            "silos-0-nom": "Silo Nord",
            "silos-0-description": "Bâtiment historique",
            "silos-0-actif": "on",
            "silos-0-cellules-TOTAL_FORMS": "1",
            "silos-0-cellules-INITIAL_FORMS": "1",
            "silos-0-cellules-MIN_NUM_FORMS": "0",
            "silos-0-cellules-MAX_NUM_FORMS": "1000",
            "silos-0-cellules-0-id": self.cellule.pk,
            "silos-0-cellules-0-nom": "Cellule Nord 1",
            "silos-0-cellules-0-type_grain": self.ble.pk,
            "silos-0-cellules-0-forme": CelluleGrain.Forme.CARREE,
            "silos-0-cellules-0-hauteur_m": "10.00",
            "silos-0-cellules-0-longueur_m": "10.00",
            "silos-0-cellules-0-actif": "on",
            "silos-1-nom": "Silo Sud",
            "silos-1-description": "Extension récente",
            "silos-1-actif": "on",
            "silos-1-cellules-TOTAL_FORMS": "2",
            "silos-1-cellules-INITIAL_FORMS": "0",
            "silos-1-cellules-MIN_NUM_FORMS": "0",
            "silos-1-cellules-MAX_NUM_FORMS": "1000",
            "silos-1-cellules-0-nom": "Cellule Sud 1",
            "silos-1-cellules-0-type_grain": self.ble.pk,
            "silos-1-cellules-0-forme": CelluleGrain.Forme.RONDE,
            "silos-1-cellules-0-hauteur_m": "12.00",
            "silos-1-cellules-0-diametre_m": "8.00",
            "silos-1-cellules-0-actif": "on",
            "silos-1-cellules-1-nom": "Cellule Sud 2",
            "silos-1-cellules-1-type_grain": self.ble.pk,
            "silos-1-cellules-1-forme": CelluleGrain.Forme.RECTANGULAIRE,
            "silos-1-cellules-1-hauteur_m": "9.00",
            "silos-1-cellules-1-longueur_m": "12.00",
            "silos-1-cellules-1-largeur_m": "6.00",
            "silos-1-cellules-1-actif": "on",
        })

        self.assertRedirects(response, reverse("site_list"))
        self.site1.refresh_from_db()
        self.assertEqual(self.site1.nom, "Herbault Centre")
        self.assertEqual(self.site1.silos.count(), 2)
        self.assertEqual(
            list(self.site1.silos.values_list("nom", flat=True)),
            ["Silo Nord", "Silo Sud"],
        )
        self.assertEqual(
            self.site1.silos.get(nom="Silo Nord").cellules.count(),
            1,
        )
        self.assertEqual(
            self.site1.silos.get(nom="Silo Sud").cellules.count(),
            2,
        )
        self.assertEqual(Silo.objects.filter(site=self.site1).count(), 2)

    def test_admin_modifie_site_avec_formulaires_supplementaires_vides(self):
        self.client.login(username="admin_t", password="testpass123")
        silo = self.cellule.silo
        donnees = {
            "nom": "Site Alpha corrigé",
            "adresse": "Adresse conservée",
            "actif": "on",
            "silos-TOTAL_FORMS": "6",
            "silos-INITIAL_FORMS": "1",
            "silos-MIN_NUM_FORMS": "0",
            "silos-MAX_NUM_FORMS": "1000",
            "silos-0-id": silo.pk,
            "silos-0-nom": silo.nom,
            "silos-0-description": "",
            "silos-0-actif": "on",
            "silos-0-cellules-TOTAL_FORMS": "2",
            "silos-0-cellules-INITIAL_FORMS": "1",
            "silos-0-cellules-MIN_NUM_FORMS": "0",
            "silos-0-cellules-MAX_NUM_FORMS": "1000",
            "silos-0-cellules-0-id": self.cellule.pk,
            "silos-0-cellules-0-nom": self.cellule.nom,
            "silos-0-cellules-0-type_grain": self.ble.pk,
            "silos-0-cellules-0-forme": self.cellule.forme,
            "silos-0-cellules-0-hauteur_m": str(self.cellule.hauteur_m),
            "silos-0-cellules-0-longueur_m": str(self.cellule.longueur_m),
            "silos-0-cellules-0-actif": "on",
            "silos-0-cellules-1-forme": CelluleGrain.Forme.RONDE,
        }
        for index in range(1, 6):
            donnees.update({
                f"silos-{index}-nom": "",
                f"silos-{index}-description": "",
                f"silos-{index}-cellules-TOTAL_FORMS": "1",
                f"silos-{index}-cellules-INITIAL_FORMS": "0",
                f"silos-{index}-cellules-MIN_NUM_FORMS": "0",
                f"silos-{index}-cellules-MAX_NUM_FORMS": "1000",
                f"silos-{index}-cellules-0-forme": CelluleGrain.Forme.RONDE,
            })

        response = self.client.post(
            reverse("site_update", args=[self.site1.pk]),
            donnees,
        )

        self.assertRedirects(response, reverse("site_list"))
        self.site1.refresh_from_db()
        self.assertEqual(self.site1.nom, "Site Alpha corrigé")
        self.assertEqual(self.site1.silos.count(), 1)
        self.assertEqual(self.site1.cellules_grain.count(), 1)

    def test_silo_enregistre_stock_physique_et_remplissage_estime(self):
        self.client.login(username="silo_t", password="testpass123")

        response = self.client.post(
            reverse("cellule_grain_relever", args=[self.cellule.pk]),
            {
                "nombre_toles_vides": "3.00",
                "forme_surface": ReleveCellule.FormeSurface.AUCUNE,
                "releve_le": "2026-08-24T10:30",
                "commentaire": "RAS",
            },
        )

        releve = ReleveCellule.objects.get(cellule=self.cellule)
        self.assertRedirects(
            response,
            reverse("cellule_grain_detail", args=[self.cellule.pk]),
        )
        self.assertEqual(releve.releve_par, self.silo)
        self.assertEqual(releve.type_grain, self.cellule.type_grain)
        self.assertEqual(releve.poids_specifique_kg_hl, Decimal("75.00"))

        formulaire = self.client.get(
            reverse("cellule_grain_relever", args=[self.cellule.pk])
        )
        self.assertNotContains(formulaire, 'name="type_grain"')
        self.assertContains(formulaire, "Blé tendre")
        self.assertEqual(releve.masse_estimee_tonnes, Decimal("600.00"))
        self.assertEqual(releve.volume_estime_m3, Decimal("800"))
        self.assertEqual(
            releve.taux_remplissage.quantize(Decimal("0.01")),
            Decimal("77.42"),
        )

        self.ble.poids_specifique_moyen = Decimal("76.00")
        self.ble.save(update_fields=["poids_specifique_moyen"])
        releve.refresh_from_db()
        self.assertEqual(releve.poids_specifique_kg_hl, Decimal("75.00"))

    def test_silo_peut_saisir_le_tonnage_manuellement(self):
        self.client.login(username="silo_t", password="testpass123")

        response = self.client.post(
            reverse("cellule_grain_relever", args=[self.cellule.pk]),
            {
                "tonnage_manuel": "500.00",
                "releve_le": "2026-08-24T10:30",
                "commentaire": "Pesée manuelle",
            },
        )

        self.assertRedirects(
            response,
            reverse("cellule_grain_detail", args=[self.cellule.pk]),
        )
        releve = ReleveCellule.objects.get(cellule=self.cellule)
        self.assertEqual(releve.tonnage_manuel, Decimal("500.00"))
        self.assertEqual(releve.masse_estimee_tonnes, Decimal("500.00"))
        self.assertEqual(releve.volume_estime_m3, Decimal("666.67"))
        self.assertEqual(
            releve.taux_remplissage.quantize(Decimal("0.01")),
            Decimal("64.52"),
        )
        self.assertContains(
            self.client.get(
                reverse("cellule_grain_detail", args=[self.cellule.pk])),
            "Saisie manuelle",
        )

    def test_capacite_totale_correspond_au_grand_cone_sortant(self):
        releve = ReleveCellule.objects.create(
            cellule=self.cellule,
            type_grain=self.ble,
            nombre_toles_vides=Decimal(0),
            forme_surface=ReleveCellule.FormeSurface.SORTANT_GRAND,
            releve_par=self.silo,
        )

        self.assertEqual(self.cellule.capacite_m3, Decimal("1033.33"))
        self.assertEqual(self.cellule.capacite_tonnes, Decimal("775.00"))
        self.assertEqual(releve.volume_estime_m3, self.cellule.capacite_m3)
        self.assertEqual(releve.masse_estimee_tonnes,
                         self.cellule.capacite_tonnes)
        self.assertEqual(releve.taux_remplissage, Decimal(100))

    def test_admin_corrige_un_stock_sans_remplacer_agent_silo(self):
        releve = ReleveCellule.objects.create(
            cellule=self.cellule,
            type_grain=self.ble,
            nombre_toles_vides=Decimal("3.00"),
            forme_surface=ReleveCellule.FormeSurface.AUCUNE,
            releve_par=self.silo,
        )
        self.client.login(username="admin_t", password="testpass123")

        self.assertEqual(
            self.client.get(reverse(
                "cellule_grain_relever", args=[self.cellule.pk]
            )).status_code,
            403,
        )
        response = self.client.post(
            reverse("releve_cellule_update", args=[releve.pk]),
            {
                "type_grain": self.ble.pk,
                "nombre_toles_vides": "4.00",
                "forme_surface": ReleveCellule.FormeSurface.RENTRANT_PETIT,
                "releve_le": "2026-08-24T11:30",
                "commentaire": "Correction administrateur",
            },
        )

        self.assertRedirects(
            response,
            reverse("cellule_grain_detail", args=[self.cellule.pk]),
        )
        releve.refresh_from_db()
        self.assertEqual(releve.nombre_toles_vides, Decimal("4.00"))
        self.assertEqual(releve.releve_par, self.silo)
        self.assertEqual(releve.commentaire, "Correction administrateur")

    def test_agent_silo_ne_peut_pas_modifier_un_stock_existant(self):
        releve = ReleveCellule.objects.create(
            cellule=self.cellule,
            type_grain=self.ble,
            nombre_toles_vides=Decimal("3.00"),
            releve_par=self.silo,
        )
        self.client.login(username="silo_t", password="testpass123")

        self.assertEqual(
            self.client.get(reverse(
                "releve_cellule_update", args=[releve.pk]
            )).status_code,
            403,
        )

    def test_actions_stock_affichees_selon_le_role(self):
        releve = ReleveCellule.objects.create(
            cellule=self.cellule,
            type_grain=self.ble,
            nombre_toles_vides=Decimal("3.00"),
            releve_par=self.silo,
        )

        self.client.login(username="silo_t", password="testpass123")
        liste_silo = self.client.get(reverse("gestion_silos"))
        detail_silo = self.client.get(reverse(
            "cellule_grain_detail", args=[self.cellule.pk]
        ))
        self.assertContains(liste_silo, "Saisir le stock")
        self.assertNotContains(
            detail_silo,
            reverse("releve_cellule_update", args=[releve.pk]),
        )

        self.client.login(username="admin_t", password="testpass123")
        liste_admin = self.client.get(reverse("gestion_silos"))
        detail_admin = self.client.get(reverse(
            "cellule_grain_detail", args=[self.cellule.pk]
        ))
        self.assertNotContains(liste_admin, "Saisir le stock")
        self.assertContains(
            detail_admin,
            reverse("releve_cellule_update", args=[releve.pk]),
        )

    def test_stock_corrige_le_volume_selon_le_cone_sur_cellule_carree(self):
        commun = {
            "cellule": self.cellule,
            "type_grain": self.ble,
            "nombre_toles_vides": Decimal("3.00"),
            "releve_par": self.silo,
        }

        sortant = ReleveCellule.objects.create(
            **commun,
            forme_surface=ReleveCellule.FormeSurface.SORTANT_MOYEN,
        )
        rentrant = ReleveCellule.objects.create(
            **commun,
            forme_surface=ReleveCellule.FormeSurface.RENTRANT_MOYEN,
        )

        self.assertEqual(sortant.volume_estime_m3, Decimal("822.22"))
        self.assertEqual(sortant.masse_estimee_tonnes, Decimal("616.67"))
        self.assertEqual(rentrant.volume_estime_m3, Decimal("777.78"))
        self.assertEqual(rentrant.masse_estimee_tonnes, Decimal("583.34"))

    def test_stock_cellule_ronde_16_par_20_avec_cone_sortant(self):
        cellule = CelluleGrain.objects.create(
            site=self.site1,
            nom="Cellule privée 16x20",
            forme=CelluleGrain.Forme.RONDE,
            diametre_m=Decimal("16.00"),
            hauteur_m=Decimal("20.00"),
            nombre_toles_hauteur=15,
        )

        releve = ReleveCellule.objects.create(
            cellule=cellule,
            type_grain=self.ble,
            nombre_toles_vides=Decimal("3.00"),
            forme_surface=ReleveCellule.FormeSurface.SORTANT_MOYEN,
            releve_par=self.silo,
        )

        self.assertEqual(releve.volume_estime_m3, Decimal("3306.35"))
        self.assertEqual(releve.masse_estimee_tonnes, Decimal("2479.76"))

    def test_saisie_stock_refuse_un_comptage_de_toles_invalide(self):
        self.client.login(username="silo_t", password="testpass123")
        url = reverse("cellule_grain_relever", args=[self.cellule.pk])
        donnees = {
            "type_grain": self.ble.pk,
            "forme_surface": ReleveCellule.FormeSurface.AUCUNE,
            "releve_le": "2026-08-24T10:30",
        }

        for valeur, erreur in (
            ("15.25", "Cette cellule comporte 15 tôles."),
            ("2.10", "Saisissez le comptage par quart de tôle."),
        ):
            with self.subTest(nombre_toles_vides=valeur):
                response = self.client.post(
                    url,
                    {**donnees, "nombre_toles_vides": valeur},
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, erreur)

        self.assertFalse(ReleveCellule.objects.filter(
            cellule=self.cellule).exists())

    def test_silo_ne_voit_que_ses_sites_et_ne_configure_pas(self):
        self.client.login(username="silo_t", password="testpass123")

        liste = self.client.get(reverse("gestion_silos"))
        self.assertEqual(liste.status_code, 200)
        self.assertContains(liste, self.cellule.nom)
        self.assertContains(liste, 'class="col-xl-3 col-md-6"', html=False)
        self.assertNotContains(liste, "Volume")
        self.assertNotContains(liste, self.cellule_autre_site.nom)
        self.assertEqual(
            self.client.get(reverse(
                "cellule_grain_detail", args=[self.cellule_autre_site.pk]
            )).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("cellule_grain_create")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse(
                "cellule_grain_update", args=[self.cellule.pk]
            )).status_code,
            403,
        )

    def test_maintenance_ne_peut_pas_acceder_a_la_gestion_silos(self):
        self.client.login(username="maint_t", password="testpass123")
        self.assertEqual(
            self.client.get(reverse("gestion_silos")).status_code,
            403,
        )


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

    def test_silo_ne_peut_declarer_panne_que_sur_son_site(self):
        equipement_site2 = Equipement.objects.create(
            site=self.site2, nom="Conv B", actif=True)
        self.client.login(username="silo_t", password='testpass123')

        response = self.client.post(
            reverse("panne_creer"),
            {
                "site": self.site2.pk,
                "equipement": equipement_site2.pk,
                "titre": "Panne hors site",
                "description": "Ne doit pas être créée",
                "priorite": Panne.Priorite.NORMALE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Panne.objects.filter(
            titre="Panne hors site").exists())

    def test_get_sites_utilisateur_maintenance_voit_tous_les_sites(self):
        maintenance = make_user("maint_multi_site_t",
                                Profile.Role.MAINTENANCE, [self.site1])
        sites = list(get_sites_utilisateur(
            maintenance).values_list("pk", flat=True))
        self.assertIn(self.site1.pk, sites)
        self.assertIn(self.site2.pk, sites)

    def test_affecter_panne_admin(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')
        r = self.client.post(
            reverse("panne_affecter", args=[panne.pk]),
            {"agent_assigne": self.maintenance.pk},
        )
        panne.refresh_from_db()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(panne.statut, Panne.Statut.AFFECTEE)
        self.assertEqual(panne.agent_assigne, self.maintenance)

    def test_affecter_panne_maintenance_interdit(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        r = self.client.post(
            reverse("panne_affecter", args=[panne.pk]),
            {"agent_assigne": self.maintenance.pk},
        )
        self.assertEqual(r.status_code, 403)

    def test_maintenance_ne_voit_que_les_pannes_assignees(self):
        panne_autre = self._panne()
        panne_autre.titre = "Panne non assignée à ce mainteneur"
        panne_autre.save(update_fields=["titre"])

        panne_assignee = self._panne()
        panne_assignee.titre = "Panne assignée à ce mainteneur"
        panne_assignee.affecte_a = self.maintenance
        panne_assignee.save(update_fields=["titre", "affecte_a"])

        self.client.login(username="maint_t", password='testpass123')
        response = self.client.get(reverse("panne_liste"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panne assignée à ce mainteneur")
        self.assertNotContains(response, "Panne non assignée à ce mainteneur")

        response_detail = self.client.get(
            reverse("panne_detail", args=[panne_autre.pk]))
        self.assertEqual(response_detail.status_code, 403)

    def test_maintenance_peut_saisir_temps_sur_panne_assignee(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["affecte_a"])
        self.maintenance.profile.tarif_horaire = Decimal("85.00")
        self.maintenance.profile.save(update_fields=["tarif_horaire"])

        self.client.login(username="maint_t", password='testpass123')
        detail_response = self.client.get(
            reverse("panne_detail", args=[panne.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Temps d’intervention")
        self.assertContains(detail_response, 'name="duree_heures"')

        response = self.client.post(
            reverse("panne_ajouter_temps_intervention", args=[panne.pk]),
            {
                "date_intervention": timezone.localdate().isoformat(),
                "duree_minutes": 90,
                "commentaire": "Intervention de test",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(panne.temps_interventions.count(), 1)
        temps = panne.temps_interventions.get()
        self.assertEqual(temps.duree_minutes, 90)
        self.assertEqual(temps.montant, Decimal("127.50"))

    def test_maintenance_voit_temps_sans_montants(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["affecte_a"])
        self.maintenance.profile.tarif_horaire = Decimal("85.00")
        self.maintenance.profile.save(update_fields=["tarif_horaire"])
        panne.temps_interventions.create(
            agent=self.maintenance,
            duree_minutes=90,
            commentaire="Intervention confidentielle",
            validee=True,
        )

        self.client.login(username="maint_t", password='testpass123')
        response = self.client.get(reverse("panne_detail", args=[panne.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="duree_heures"')
        self.assertContains(response, "90 min")
        self.assertNotContains(response, "127,50 €")
        self.assertNotContains(response, "Total global panne")

        self.client.login(username="admin_t", password='testpass123')
        response = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(response, "127,50 €")
        self.assertContains(response, "Total global panne")

    def test_admin_peut_valider_temps_intervention_et_calcule_total_global(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["affecte_a"])
        self.maintenance.profile.tarif_horaire = Decimal("85.00")
        self.maintenance.profile.save(update_fields=["tarif_horaire"])
        temps = panne.temps_interventions.create(
            agent=self.maintenance,
            duree_minutes=90,
            commentaire="À valider",
        )
        temps.validee = False
        temps.save(update_fields=["validee"])
        Facture.objects.create(
            panne=panne,
            numero="FAC-GLOBAL",
            fournisseur="Fourni SA",
            montant_ht="50.00",
            montant_ttc="60.00",
        )

        self.client.login(username="admin_t", password='testpass123')
        response = self.client.post(
            reverse("panne_valider_temps_intervention",
                    args=[panne.pk, temps.pk]),
        )

        temps.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(temps.validee)
        self.assertEqual(panne.total_temps_minutes, 90)
        self.assertEqual(panne.cout_total_intervention, Decimal("127.50"))
        self.assertEqual(panne.cout_total_global, Decimal("177.50"))

    def test_admin_voit_techniciens_autres_sites(self):
        panne = self._panne()
        autre_maintenance = make_user(
            "maint_site2_t", Profile.Role.MAINTENANCE, [self.site2])
        self.client.login(username="admin_t", password='testpass123')
        r = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'value="{autre_maintenance.pk}"')

    def test_admin_voit_formulaire_affectation_sur_detail(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')
        r = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="affecte_a"')
        self.assertContains(r, 'Assigner')

    def test_admin_peut_reassigner_une_panne_en_cours(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.EN_COURS
        panne.save(update_fields=["affecte_a", "statut"])
        autre_maintenance = make_user(
            "maint_remplacant_t", Profile.Role.MAINTENANCE)
        self.client.login(username="admin_t", password='testpass123')

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(detail, 'name="affecte_a"')
        self.assertContains(detail, 'Réassigner')

        response = self.client.post(
            reverse("panne_affecter", args=[panne.pk]),
            {"affecte_a": autre_maintenance.pk},
        )

        self.assertEqual(response.status_code, 302)
        panne.refresh_from_db()
        self.assertEqual(panne.affecte_a, autre_maintenance)
        self.assertEqual(panne.statut, Panne.Statut.EN_COURS)

    def test_admin_voit_et_utilise_bouton_suppression_panne(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))

        self.assertContains(detail, reverse("panne_delete", args=[panne.pk]))
        self.assertContains(detail, "Supprimer la panne")

        response = self.client.post(reverse("panne_delete", args=[panne.pk]))

        self.assertRedirects(response, reverse("panne_liste"))
        self.assertFalse(Panne.objects.filter(pk=panne.pk).exists())

    def test_admin_modifie_la_priorite_d_une_panne(self):
        panne = self._panne()
        self.client.login(username="admin_t", password="testpass123")

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(detail, 'name="priorite"')

        response = self.client.post(
            reverse("panne_modifier_priorite", args=[panne.pk]),
            {"priorite": Panne.Priorite.CRITIQUE},
        )

        self.assertRedirects(response, reverse(
            "panne_detail", args=[panne.pk]))
        panne.refresh_from_db()
        self.assertEqual(panne.priorite, Panne.Priorite.CRITIQUE)

        self.client.login(username="silo_t", password="testpass123")
        response = self.client.post(
            reverse("panne_modifier_priorite", args=[panne.pk]),
            {"priorite": Panne.Priorite.BASSE},
        )
        self.assertEqual(response.status_code, 403)
        panne.refresh_from_db()
        self.assertEqual(panne.priorite, Panne.Priorite.CRITIQUE)

    def test_silo_declarant_modifie_sa_panne_nouvelle(self):
        panne = self._panne()
        self.client.login(username="silo_t", password='testpass123')

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(detail, reverse("panne_update", args=[panne.pk]))
        self.assertContains(detail, reverse("panne_delete", args=[panne.pk]))

        response = self.client.post(
            reverse("panne_update", args=[panne.pk]),
            {
                "site": self.site1.pk,
                "equipement": self.eq1.pk,
                "titre": "Panne corrigée par le déclarant",
                "description": "Description mise à jour",
                "priorite": Panne.Priorite.HAUTE,
            },
        )
        self.assertRedirects(response, reverse(
            "panne_detail", args=[panne.pk]))
        panne.refresh_from_db()
        self.assertEqual(panne.titre, "Panne corrigée par le déclarant")
        self.assertEqual(panne.statut, Panne.Statut.NOUVELLE)

        response = self.client.post(reverse("panne_delete", args=[panne.pk]))
        self.assertRedirects(response, reverse("panne_liste"))
        self.assertFalse(Panne.objects.filter(pk=panne.pk).exists())

    def test_silo_ne_modifie_ni_supprime_panne_non_nouvelle(self):
        panne = self._panne()
        panne.statut = Panne.Statut.AFFECTEE
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["statut", "affecte_a"])
        self.client.login(username="silo_t", password='testpass123')

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertNotContains(detail, reverse(
            "panne_update", args=[panne.pk]))
        self.assertNotContains(detail, reverse(
            "panne_delete", args=[panne.pk]))
        self.assertEqual(
            self.client.get(
                reverse("panne_update", args=[panne.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("panne_delete", args=[panne.pk])).status_code,
            404,
        )
        self.assertTrue(Panne.objects.filter(pk=panne.pk).exists())

    def test_autre_silo_ne_modifie_ni_supprime_panne_nouvelle(self):
        panne = self._panne()
        self.client.login(username="silo2_t", password='testpass123')

        self.assertEqual(
            self.client.get(
                reverse("panne_update", args=[panne.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("panne_delete", args=[panne.pk])).status_code,
            404,
        )
        self.assertTrue(Panne.objects.filter(pk=panne.pk).exists())

    def test_panne_archivee_absente_des_pannes_recentes(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.CLOTUREE
        panne.save(update_fields=["affecte_a", "statut"])

        for username in ("admin_t", "maint_t", "silo_t"):
            with self.subTest(username=username):
                self.client.login(username=username, password='testpass123')
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, panne.titre)

    def test_dashboard_admin_detaille_les_pannes_recentes(self):
        panne_non_affectee = self._panne()
        panne_non_affectee.titre = "Panne récente non affectée"
        panne_non_affectee.save(update_fields=["titre"])
        panne_affectee = self._panne()
        panne_affectee.titre = "Panne récente déjà affectée"
        panne_affectee.affecte_a = self.maintenance
        panne_affectee.statut = Panne.Statut.AFFECTEE
        panne_affectee.save(update_fields=["titre", "affecte_a", "statut"])
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        pannes_recentes = list(response.context["pannes_recentes"])
        self.assertIn(panne_non_affectee, pannes_recentes)
        self.assertIn(panne_affectee, pannes_recentes)
        self.assertContains(response, self.site1.nom)
        self.assertContains(response, self.maintenance.username)
        self.assertContains(response, "Non affectée")

    def test_dashboard_admin_detaille_les_preventives_recentes(self):
        preventive = MaintenancePreventive.objects.create(
            site=self.site1,
            equipement=self.eq1,
            affecte_a=self.silo,
            created_by=self.admin,
            titre="Contrôle préventif détaillé",
            description="Instructions",
            date_echeance=timezone.now() + timedelta(days=2),
        )
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            preventive,
            list(response.context["preventives_recentes"]),
        )
        self.assertContains(response, preventive.titre)
        self.assertContains(response, self.silo.username)
        self.assertContains(response, "Échéance")

    def test_dashboard_maintenance_affiche_preventives_des_equipements_en_panne(self):
        autre_equipement = Equipement.objects.create(
            site=self.site1, nom="Convoyeur sans panne", actif=True)
        panne = self._panne()
        panne.equipement = self.eq1
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.AFFECTEE
        panne.save(update_fields=["equipement", "affecte_a", "statut"])
        preventive_liee = MaintenancePreventive.objects.create(
            site=self.site1,
            equipement=self.eq1,
            created_by=self.admin,
            affecte_a=self.silo,
            titre="Préventive liée à la panne",
            description="Contrôle ciblé",
            date_echeance=timezone.now() + timedelta(days=1),
        )
        preventive_sans_rapport = MaintenancePreventive.objects.create(
            site=self.site1,
            equipement=autre_equipement,
            created_by=self.admin,
            affecte_a=self.silo,
            titre="Préventive sans rapport",
            description="Autre équipement",
            date_echeance=timezone.now() + timedelta(days=1),
        )
        self.client.login(username="maint_t", password='testpass123')

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        preventives_recentes = list(response.context["preventives_recentes"])
        self.assertIn(preventive_liee, preventives_recentes)
        self.assertNotIn(preventive_sans_rapport, preventives_recentes)

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

    def test_maintenance_assignee_peut_changer_statut_depuis_detail(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.AFFECTEE
        panne.save(update_fields=["affecte_a", "statut"])
        self.client.login(username="maint_t", password='testpass123')

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(detail, "Changer le statut")
        self.assertContains(detail, f'value="{Panne.Statut.EN_COURS}"')
        self.assertContains(detail, f'value="{Panne.Statut.ATTENTE_PIECE}"')
        self.assertContains(detail, f'value="{Panne.Statut.IMPREVUS}"')
        self.assertContains(detail, f'value="{Panne.Statut.RESOLUE}"')

        response = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {"nouveau_statut": Panne.Statut.EN_COURS,
                "commentaire": "Prise en charge"},
        )
        panne.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(panne.statut, Panne.Statut.EN_COURS)

    def test_changement_statut_conserve_le_fichier_joint(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.AFFECTEE
        panne.save(update_fields=["affecte_a", "statut"])
        self.client.login(username="maint_t", password='testpass123')
        fichier = SimpleUploadedFile(
            "diagnostic.pdf",
            b"%PDF-1.4\ndiagnostic",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {
                "nouveau_statut": Panne.Statut.EN_COURS,
                "commentaire": "Diagnostic joint",
                "medias": fichier,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 302)
        media = PanneMedia.objects.get(panne=panne)
        self.assertEqual(media.nom_original, "diagnostic.pdf")
        self.assertEqual(media.ajoute_par, self.maintenance)

    def test_maintenance_voit_les_statuts_operationnels_sans_archivage(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.EN_COURS
        panne.save(update_fields=["affecte_a", "statut"])
        self.client.login(username="maint_t", password='testpass123')

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))

        self.assertContains(detail, f'value="{Panne.Statut.ATTENTE_PIECE}"')
        self.assertContains(detail, f'value="{Panne.Statut.IMPREVUS}"')
        self.assertContains(detail, f'value="{Panne.Statut.RESOLUE}"')
        self.assertNotContains(detail, f'value="{Panne.Statut.CLOTUREE}"')

    def test_maintenance_non_assignee_ne_peut_pas_changer_statut(self):
        panne = self._panne()
        autre_maintenance = make_user(
            "maint_non_assigne_t", Profile.Role.MAINTENANCE)
        self.client.login(username="maint_non_assigne_t",
                          password='testpass123')

        response = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {"nouveau_statut": Panne.Statut.AFFECTEE},
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_conserve_les_changements_de_statut_panne(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.AFFECTEE
        panne.save(update_fields=["affecte_a", "statut"])
        self.client.login(username="admin_t", password="testpass123")

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Changer le statut")
        self.assertContains(detail, f'value="{Panne.Statut.EN_COURS}"')

        response = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {
                "nouveau_statut": Panne.Statut.EN_COURS,
                "commentaire": "Mise à jour administrative",
            },
        )

        self.assertEqual(response.status_code, 302)
        panne.refresh_from_db()
        self.assertEqual(panne.statut, Panne.Statut.EN_COURS)

        detail = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(detail, f'value="{Panne.Statut.ATTENTE_PIECE}"')
        self.assertContains(detail, f'value="{Panne.Statut.IMPREVUS}"')
        self.assertContains(detail, f'value="{Panne.Statut.RESOLUE}"')

    def test_parcours_complet_panne_affectation_intervention_et_archivage(self):
        panne = self._panne()
        self.maintenance.profile.tarif_horaire = Decimal("80.00")
        self.maintenance.profile.save(update_fields=["tarif_horaire"])

        self.client.login(username="admin_t", password="testpass123")
        self.client.post(
            reverse("panne_affecter", args=[panne.pk]),
            {"affecte_a": self.maintenance.pk},
        )
        panne.refresh_from_db()
        self.assertEqual(panne.statut, Panne.Statut.AFFECTEE)
        self.assertEqual(panne.affecte_a, self.maintenance)

        self.client.login(username="maint_t", password="testpass123")
        for statut in (
            Panne.Statut.EN_COURS,
            Panne.Statut.IMPREVUS,
            Panne.Statut.EN_COURS,
            Panne.Statut.ATTENTE_PIECE,
            Panne.Statut.RESOLUE,
        ):
            response = self.client.post(
                reverse("panne_changer_statut", args=[panne.pk]),
                {"nouveau_statut": statut, "commentaire": "Suivi intervention"},
            )
            self.assertEqual(response.status_code, 302)
            panne.refresh_from_db()
            self.assertEqual(panne.statut, statut)

        response = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {"nouveau_statut": Panne.Statut.CLOTUREE},
        )
        self.assertEqual(response.status_code, 403)
        panne.refresh_from_db()
        self.assertEqual(panne.statut, Panne.Statut.RESOLUE)

        self.client.login(username="admin_t", password="testpass123")
        response = self.client.post(
            reverse("panne_ajouter_facture", args=[panne.pk]),
            {
                "numero": "FAC-PARCOURS",
                "fournisseur": "Fourni SA",
                "montant_ht": "100.00",
                "montant_ttc": "120.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Facture.objects.filter(
            panne=panne, numero="FAC-PARCOURS").exists())

        response = self.client.post(
            reverse("panne_ajouter_temps_intervention", args=[panne.pk]),
            {
                "date_intervention": timezone.localdate().isoformat(),
                "duree_heures": "1.50",
                "commentaire": "Temps saisi par l'administration",
            },
        )
        self.assertEqual(response.status_code, 302)
        temps = PanneTempsIntervention.objects.get(panne=panne)
        self.assertEqual(temps.agent, self.maintenance)
        self.assertEqual(temps.duree_minutes, 90)
        self.assertTrue(temps.validee)

        response = self.client.post(
            reverse("panne_changer_statut", args=[panne.pk]),
            {"nouveau_statut": Panne.Statut.CLOTUREE},
        )
        self.assertEqual(response.status_code, 302)
        panne.refresh_from_db()
        self.assertEqual(panne.statut, Panne.Statut.CLOTUREE)

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
            createur=self.admin,
            destinataire=self.silo,
            titre="Tâche test",
            instructions="Instructions",
            echeance=timezone.now() + timedelta(days=7),
            statut=statut,
        )

    def test_admin_cree_et_envoie_preventive(self):
        self.client.login(username="admin_t", password='testpass123')
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
        preventive = MaintenancePreventive.objects.get(titre="Nouvelle tâche")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(preventive.createur, self.admin)
        self.assertEqual(preventive.destinataire, self.silo)

        r = self.client.post(
            reverse("preventive_envoyer", args=[preventive.pk]))
        preventive.refresh_from_db()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(preventive.statut,
                         MaintenancePreventive.Statut.ENVOYEE)

    def test_admin_cree_une_preventive_mensuelle(self):
        self.client.login(username="admin_t", password="testpass123")
        response = self.client.post(
            reverse("preventive_creer"),
            {
                "site": self.site1.pk,
                "affecte_a": self.silo.pk,
                "titre": "Contrôle mensuel",
                "description": "Contrôler les organes de sécurité",
                "date_echeance": "2030-01-31T10:00",
                "periodicite": MaintenancePreventive.Periodicite.MENSUELLE,
                "recurrence_active": "on",
                "recurrence_jusquau": "2030-12-31",
            },
        )

        self.assertEqual(response.status_code, 302)
        preventive = MaintenancePreventive.objects.get(
            titre="Contrôle mensuel")
        self.assertEqual(
            preventive.periodicite,
            MaintenancePreventive.Periodicite.MENSUELLE,
        )
        self.assertTrue(preventive.recurrence_active)

    def test_calcul_des_echeances_periodiques_respecte_les_fins_de_mois(self):
        preventive = self._preventive()
        preventive.date_echeance = timezone.datetime(
            2032, 1, 31, 10, tzinfo=timezone.get_current_timezone()
        )

        attentes = (
            (MaintenancePreventive.Periodicite.MENSUELLE, (2032, 2, 29)),
            (MaintenancePreventive.Periodicite.TRIMESTRIELLE, (2032, 4, 30)),
            (MaintenancePreventive.Periodicite.ANNUELLE, (2033, 1, 31)),
        )
        for periodicite, date_attendue in attentes:
            with self.subTest(periodicite=periodicite):
                preventive.periodicite = periodicite
                suivante = preventive.prochaine_echeance_apres(
                    preventive.date_echeance
                )
                self.assertEqual(
                    (suivante.year, suivante.month, suivante.day),
                    date_attendue,
                )

    def test_generation_mensuelle_est_automatique_et_idempotente(self):
        premiere_echeance = timezone.now() + timedelta(days=1)
        preventive = self._preventive(MaintenancePreventive.Statut.ENVOYEE)
        preventive.date_echeance = premiere_echeance
        preventive.periodicite = MaintenancePreventive.Periodicite.MENSUELLE
        preventive.recurrence_active = True
        preventive.save(update_fields=[
            "date_echeance", "periodicite", "recurrence_active", "updated_at"
        ])

        call_command("generate_recurring_preventives", days_ahead=40)
        call_command("generate_recurring_preventives", days_ahead=40)

        occurrence = preventive.occurrences.get()
        self.assertEqual(
            occurrence.statut, MaintenancePreventive.Statut.ENVOYEE
        )
        self.assertEqual(occurrence.affecte_a, self.silo)
        self.assertEqual(preventive.occurrences.count(), 1)
        self.assertTrue(
            Notification.objects.filter(
                utilisateur=self.silo,
                type_notif=Notification.TypeNotif.PREVENTIVE_RECUE,
                lien=f"/preventives/{occurrence.pk}/",
            ).exists()
        )

    def test_maintenance_ne_peut_pas_creer_ou_envoyer_preventive(self):
        self.client.login(username="maint_t", password='testpass123')
        response = self.client.get(reverse("preventive_creer"))
        self.assertEqual(response.status_code, 403)

        preventive = self._preventive(MaintenancePreventive.Statut.BROUILLON)
        response = self.client.post(
            reverse("preventive_envoyer", args=[preventive.pk]))
        self.assertEqual(response.status_code, 403)

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

    def test_destinataire_voit_actions_adaptees_au_statut_preventive(self):
        self.client.login(username="silo_t", password='testpass123')
        attentes = (
            (MaintenancePreventive.Statut.ENVOYEE, "Marquer comme reçue"),
            (MaintenancePreventive.Statut.RECUE, "Démarrer"),
            (MaintenancePreventive.Statut.EN_COURS, "Terminer (compte rendu)"),
        )

        for statut, libelle in attentes:
            preventive = self._preventive(statut)
            response = self.client.get(
                reverse("preventive_detail", args=[preventive.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, libelle)

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

    def test_silo_termine_avec_fichier_protege(self):
        p = self._preventive(MaintenancePreventive.Statut.EN_COURS)
        self.client.login(username="silo_t", password='testpass123')
        fichier = SimpleUploadedFile(
            "compte-rendu.pdf",
            b"%PDF-1.4\npreventive",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("preventive_terminer", args=[p.pk]),
            {"retour_intervention": "Travail réalisé", "medias": fichier},
            format="multipart",
        )

        self.assertRedirects(response, reverse(
            "preventive_detail", args=[p.pk]))
        media = PreventiveMedia.objects.get(preventive=p)
        self.assertEqual(media.nom_original, "compte-rendu.pdf")
        self.assertEqual(
            self.client.get(
                reverse("preventive_media_telecharger", args=[media.pk])
            ).status_code,
            200,
        )

        self.client.login(username="maint_t", password='testpass123')
        self.assertEqual(
            self.client.get(
                reverse("preventive_media_telecharger", args=[media.pk])
            ).status_code,
            403,
        )

    def test_retour_obligatoire(self):
        p = self._preventive(MaintenancePreventive.Statut.EN_COURS)
        self.client.login(username="silo_t", password='testpass123')
        r = self.client.post(
            reverse("preventive_terminer", args=[p.pk]),
            {"retour": ""},  # vide → erreur
        )
        p.refresh_from_db()
        self.assertEqual(
            p.statut, MaintenancePreventive.Statut.EN_COURS)  # inchangé

    def test_admin_valide_le_retour(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        self.client.login(username="admin_t", password='testpass123')
        self.client.post(
            reverse("preventive_valider", args=[p.pk]),
            {"decision": "valider", "commentaire": ""},
        )
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.ARCHIVEE)
        self.assertTrue(Notification.objects.filter(
            utilisateur=self.silo,
            type_notif=Notification.TypeNotif.PREVENTIVE_VALIDEE,
        ).exists())
        self.assertEqual(
            list(HistoriquePreventive.objects.filter(
                preventive=p,
            ).order_by("creee_le", "pk").values_list(
                "nouveau_statut", flat=True
            )),
            [
                MaintenancePreventive.Statut.VALIDEE,
                MaintenancePreventive.Statut.ARCHIVEE,
            ],
        )

    def test_preventive_archivee_disparait_pour_silo_et_reste_cote_admin(self):
        preventive = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        media = PreventiveMedia.objects.create(
            preventive=preventive,
            fichier=SimpleUploadedFile(
                "rapport-preventive.pdf", b"%PDF-1.4\narchive"
            ),
            nom_original="rapport-preventive.pdf",
            ajoute_par=self.silo,
        )
        self.client.login(username="admin_t", password="testpass123")
        self.client.post(
            reverse("preventive_valider", args=[preventive.pk]),
            {"decision": "valider", "commentaire": "Travail conforme"},
        )
        preventive.refresh_from_db()

        admin_dashboard = self.client.get(reverse("dashboard"))
        admin_archives = self.client.get(
            reverse("preventive_liste"),
            {"statut": MaintenancePreventive.Statut.ARCHIVEE},
        )
        self.assertIn(
            preventive,
            list(admin_dashboard.context["preventives_recentes"]),
        )
        self.assertContains(admin_archives, preventive.titre)

        self.client.login(username="silo_t", password="testpass123")
        silo_dashboard = self.client.get(reverse("dashboard"))
        silo_liste = self.client.get(reverse("preventive_liste"))
        silo_detail = self.client.get(
            reverse("preventive_detail", args=[preventive.pk])
        )
        self.assertNotIn(
            preventive,
            list(silo_dashboard.context["preventives_recentes"]),
        )
        self.assertNotContains(silo_liste, preventive.titre)
        self.assertEqual(silo_detail.status_code, 404)
        self.assertEqual(
            self.client.get(reverse(
                "preventive_media_telecharger", args=[media.pk]
            )).status_code,
            403,
        )

    def test_maintenance_valide_preventive_liee_a_sa_panne_active(self):
        panne = Panne.objects.create(
            site=self.site1,
            equipement=self.eq1,
            signale_par=self.silo,
            affecte_a=self.maintenance,
            titre="Panne liée à la préventive",
            description="Test",
            statut=Panne.Statut.EN_COURS,
        )
        preventive = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        preventive.equipement = panne.equipement
        preventive.save(update_fields=["equipement"])
        self.client.login(username="maint_t", password='testpass123')

        detail = self.client.get(
            reverse("preventive_detail", args=[preventive.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Valider / Rejeter")

        response = self.client.post(
            reverse("preventive_valider", args=[preventive.pk]),
            {"decision": "valider", "commentaire": "Contrôle effectué"},
        )
        self.assertEqual(response.status_code, 302)
        preventive.refresh_from_db()
        self.assertEqual(
            preventive.statut, MaintenancePreventive.Statut.VALIDEE)

    def test_maintenance_marque_preventive_liee_comme_terminee_sans_voir_fichiers(self):
        Panne.objects.create(
            site=self.site1,
            equipement=self.eq1,
            signale_par=self.silo,
            affecte_a=self.maintenance,
            titre="Panne active liée",
            description="Test",
            statut=Panne.Statut.EN_COURS,
        )
        preventive = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        preventive.equipement = self.eq1
        preventive.save(update_fields=["equipement"])
        self.client.login(username="maint_t", password='testpass123')

        detail = self.client.get(
            reverse("preventive_detail", args=[preventive.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Marquer comme terminée")
        self.assertNotContains(detail, "Fichiers joints")

        response = self.client.post(
            reverse("preventive_changer_statut", args=[preventive.pk]),
            {"nouveau_statut": MaintenancePreventive.Statut.EFFECTUEE},
        )
        self.assertEqual(response.status_code, 302)
        preventive.refresh_from_db()
        self.assertEqual(
            preventive.statut, MaintenancePreventive.Statut.EFFECTUEE)

    def test_maintenance_ne_termine_pas_preventive_sans_panne_liee(self):
        preventive = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        preventive.equipement = self.eq1
        preventive.save(update_fields=["equipement"])
        self.client.login(username="maint_t", password='testpass123')

        response = self.client.post(
            reverse("preventive_changer_statut", args=[preventive.pk]),
            {"nouveau_statut": MaintenancePreventive.Statut.EFFECTUEE},
        )
        self.assertEqual(response.status_code, 403)
        preventive.refresh_from_db()
        self.assertEqual(
            preventive.statut, MaintenancePreventive.Statut.A_VALIDER)

    def test_maintenance_ne_valide_pas_preventive_sans_panne_liee(self):
        autre_equipement = Equipement.objects.create(
            site=self.site1, nom="Équipement sans panne affectée", actif=True)
        Panne.objects.create(
            site=self.site1,
            equipement=autre_equipement,
            signale_par=self.silo,
            affecte_a=self.maintenance,
            titre="Ancienne panne terminée",
            description="Test",
            statut=Panne.Statut.RESOLUE,
        )
        preventive = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        preventive.equipement = autre_equipement
        preventive.save(update_fields=["equipement"])
        self.client.login(username="maint_t", password='testpass123')

        detail = self.client.get(
            reverse("preventive_detail", args=[preventive.pk]))
        self.assertEqual(detail.status_code, 404)

        response = self.client.post(
            reverse("preventive_valider", args=[preventive.pk]),
            {"decision": "valider", "commentaire": "Tentative interdite"},
        )
        self.assertEqual(response.status_code, 403)
        preventive.refresh_from_db()
        self.assertEqual(
            preventive.statut, MaintenancePreventive.Statut.A_VALIDER)

    def test_admin_voit_action_validation_et_retour_preventive(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        p.retour = "Travail effectué et contrôlé."
        p.save(update_fields=["retour_intervention"])
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.get(reverse("preventive_detail", args=[p.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Travail effectué et contrôlé.")
        self.assertContains(response, "Valider / Rejeter")

    def test_tout_admin_peut_traiter_le_retour_preventive(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        autre_admin = make_user("admin_remplacant_t", Profile.Role.ADMIN)
        self.client.login(username="admin_remplacant_t",
                          password='testpass123')

        response = self.client.get(reverse("preventive_detail", args=[p.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Valider / Rejeter")

        response = self.client.post(
            reverse("preventive_valider", args=[p.pk]),
            {"decision": "valider", "commentaire": "Validé par le relais"},
        )
        self.assertEqual(response.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.ARCHIVEE)

    def test_admin_rejette_avec_commentaire(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        self.client.login(username="admin_t", password='testpass123')
        self.client.post(
            reverse("preventive_valider", args=[p.pk]),
            {"decision": "rejeter", "commentaire": "Retour insuffisant."},
        )
        p.refresh_from_db()
        self.assertEqual(p.statut, MaintenancePreventive.Statut.REJETEE)

    def test_rejet_sans_commentaire_interdit(self):
        p = self._preventive(MaintenancePreventive.Statut.A_VALIDER)
        self.client.login(username="admin_t", password='testpass123')
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

    def test_upload_pdf_refuse_dans_medias_terrain(self):
        panne = self._panne()
        self.client.login(username="silo_t", password='testpass123')
        fichier = SimpleUploadedFile(
            "document.pdf", b"%PDF-1.4\ndocument terrain")
        response = self.client.post(
            reverse("panne_ajouter_media", args=[panne.pk]),
            {"medias": fichier},
            format="multipart",
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PanneMedia.objects.filter(panne=panne).exists())

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

    def test_photos_videos_terrain_sont_separees_des_factures(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["affecte_a"])
        media = PanneMedia.objects.create(
            panne=panne,
            fichier=SimpleUploadedFile("terrain.png", _png_file().read()),
            nom_original="terrain.png",
            ajoute_par=self.silo,
        )
        Facture.objects.create(
            panne=panne,
            numero="FAC-PRIVEE",
            fournisseur="Fourni SA",
            montant_ht="100.00",
            montant_ttc="120.00",
        )

        for username in ("silo_t", "maint_t"):
            with self.subTest(username=username):
                self.client.login(username=username, password='testpass123')
                response = self.client.get(
                    reverse("panne_detail", args=[panne.pk]))
                self.assertContains(response, "Photos et vidéos terrain")
                self.assertContains(response, media.nom_original)
                self.assertNotContains(response, "Factures")
                self.assertNotContains(response, "FAC-PRIVEE")

        self.client.login(username="admin_t", password='testpass123')
        response = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertContains(response, "Photos et vidéos terrain")
        self.assertContains(response, "Factures administratives")
        self.assertContains(response, "FAC-PRIVEE")

    @patch("maintenance.models.optimiser_media_televerse")
    def test_media_terrain_est_remplace_par_sa_version_optimisee(self, optimiser):
        panne = self._panne()
        optimiser.return_value = SimpleUploadedFile(
            "terrain.webp",
            b"contenu optimise",
            content_type="image/webp",
        )

        media = PanneMedia.objects.create(
            panne=panne,
            fichier=SimpleUploadedFile(
                "terrain.jpg",
                b"contenu original plus volumineux",
                content_type="image/jpeg",
            ),
            nom_original="terrain.jpg",
            ajoute_par=self.silo,
        )

        self.assertTrue(media.fichier.name.endswith("terrain.webp"))
        self.assertEqual(media.nom_original, "terrain.jpg")
        self.assertEqual(media.nom_telechargement, "terrain.webp")
        optimiser.assert_called_once()

    @patch("maintenance.models.optimiser_media_televerse", return_value=None)
    def test_media_terrain_conserve_original_si_optimisation_impossible(
        self, optimiser
    ):
        panne = self._panne()

        media = PanneMedia.objects.create(
            panne=panne,
            fichier=SimpleUploadedFile(
                "terrain.png",
                b"contenu original",
                content_type="image/png",
            ),
            nom_original="terrain.png",
            ajoute_par=self.silo,
        )

        self.assertTrue(media.fichier.name.endswith("terrain.png"))
        self.assertEqual(media.nom_telechargement, "terrain.png")
        optimiser.assert_called_once()

    def test_media_terrain_telechargeable_uniquement_par_acteurs_de_la_panne(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["affecte_a"])
        media = PanneMedia.objects.create(
            panne=panne,
            fichier=SimpleUploadedFile("terrain.png", _png_file().read()),
            nom_original="terrain.png",
            ajoute_par=self.silo,
        )

        for username in ("admin_t", "silo_t", "maint_t"):
            with self.subTest(username=username):
                self.client.login(username=username, password='testpass123')
                response = self.client.get(
                    reverse("panne_media_telecharger", args=[media.pk]))
                self.assertEqual(response.status_code, 200)

        maintenance_non_affecte = make_user(
            "maint2_t", Profile.Role.MAINTENANCE)
        for username in ("silo2_t", maintenance_non_affecte.username):
            with self.subTest(username=username):
                self.client.login(username=username, password='testpass123')
                response = self.client.get(
                    reverse("panne_media_telecharger", args=[media.pk]))
                self.assertEqual(response.status_code, 403)
                response = self.client.get(media.fichier.url)
                self.assertEqual(response.status_code, 403)


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

    def test_liste_factures_filtre_par_site_et_periode(self):
        self.client.login(username="admin_t", password="testpass123")
        panne_site_1 = self._panne()
        panne_site_2 = Panne.objects.create(
            site=self.site2,
            declarant=self.silo2,
            titre="Panne autre site",
            description="Test",
            statut=Panne.Statut.EN_COURS,
        )
        facture_site_1 = Facture.objects.create(
            panne=panne_site_1,
            numero="SITE-1-AOUT",
            fournisseur="Fournisseur site 1",
            montant_ht=Decimal("100.00"),
            montant_ttc=Decimal("120.00"),
            date_facture=date(2026, 8, 10),
        )
        facture_site_2 = Facture.objects.create(
            panne=panne_site_2,
            numero="SITE-2-SEPT",
            fournisseur="Fournisseur site 2",
            montant_ht=Decimal("200.00"),
            montant_ttc=Decimal("240.00"),
            date_facture=date(2026, 9, 10),
        )

        response = self.client.get(reverse("facture_list"), {
            "site": self.site1.pk,
            "start_date": "2026-08-31",
            "end_date": "2026-08-01",
        }, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, facture_site_1.numero)
        self.assertNotContains(response, facture_site_2.numero)

    def test_extraction_distingue_entete_echeance_et_totaux(self):
        contenu = """AXEREAL SERVICES SAS
FACTURE N° FAC-2026-0042
Date de facture : 22/08/2026
Date échéance : 21/09/2026
Sous-total HT 1 250,00 EUR
TVA 20 % 250,00 EUR
Net à payer 1 500,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-source.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "FAC-2026-0042")
        self.assertEqual(resultat["fournisseur"], "AXEREAL SERVICES SAS")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-22")
        self.assertEqual(resultat["montant_ht"], Decimal("1250.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("250.00"))
        self.assertEqual(resultat["taux_tva"], Decimal(20))
        self.assertEqual(resultat["montant_ttc"], Decimal("1500.00"))

    def test_detection_rejette_un_releve_financier_non_facture(self):
        contenu = """RELEVE DE COMPTE
Date : 22/08/2026
Solde initial : 1 250,00 EUR
Solde final : 1 500,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "releve.txt"

        resultat = extract_invoice_data_from_document(fichier)

        detection = resultat["_detection"]
        self.assertFalse(detection["signaux"]["mot_facture"])
        self.assertIn(
            "Le document ne contient pas de libellé facture clairement identifié",
            detection["alertes"],
        )
        self.assertLess(detection["score_global"], 80)

    def test_extraction_complete_un_montant_tva_absent(self):
        contenu = """MAINTENANCE DU GRAIN SARL
Numéro de facture : INV-7788
Date d'émission : 03/07/2026
Total HT : 800.00 EUR
Total TTC : 960.00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "invoice.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["montant_ht"], Decimal("800.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("160.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("960.00"))

    def test_extraction_avancee_lit_les_valeurs_sur_la_ligne_suivante(self):
        contenu = """SAS MOULINS TECHNIQUES
FACTURE
N°
MT-2026-918
Date de facture
18/08/2026
TOTAL HT
2 400,00 EUR
TVA 20 %
480,00 EUR
NET À PAYER
2 880,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-zones.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "MT-2026-918")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-18")
        self.assertEqual(resultat["montant_ht"], Decimal("2400.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("480.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("2880.00"))

    def test_extraction_avancee_ne_confond_pas_client_et_fournisseur(self):
        contenu = """FACTURE FAC-77881
Client : AXEREAL SILO DE TEST
Adresse de facturation : 1 rue du Silo
Fournisseur : ÉLECTROMÉCANIQUE DURAND SAS
SIRET 123 456 789 00012
Date d'émission : 19/08/2026
Total HT : 500,00 EUR
TVA 20 % : 100,00 EUR
Total TTC : 600,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-client-fournisseur.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(
            resultat["fournisseur"], "ÉLECTROMÉCANIQUE DURAND SAS"
        )
        self.assertNotEqual(resultat["fournisseur"], "AXEREAL SILO DE TEST")

    def test_extraction_avancee_signale_une_incoherence_comptable(self):
        contenu = """ATELIER SILO SARL
Facture N° AS-42
Date facture : 20/08/2026
Total HT : 1 000,00 EUR
Total TVA : 200,00 EUR
Total TTC : 1 250,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-incoherente.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertIn("alertes", resultat["_detection"])
        self.assertIn("Montants comptables incohérents",
                      resultat["_detection"]["alertes"])
        self.assertLess(resultat["_detection"]["score_global"], 80)

    def test_extraction_aligne_les_totaux_presentes_en_colonnes(self):
        contenu = """DURAND MAINTENANCE SAS
Facture N° DM-2026-88
Date de facture : 21/08/2026
Total HT        TVA 20 %        Total TTC
1 250,00 EUR    250,00 EUR      1 500,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-colonnes.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["montant_ht"], Decimal("1250.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("250.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("1500.00"))
        self.assertEqual(resultat["taux_tva"], Decimal("20"))

    def test_extraction_multipage_utilise_entete_et_derniere_page(self):
        contenu = """contact@durand-maintenance.fr
12 rue des Ateliers
Facture N° DM-2026-104
Date de facture : 22/08/2026
Client : AXEREAL SILO
Acompte TTC : 300,00 EUR
\fDétail des interventions
Sous-total intermédiaire : 900,00 EUR
\fRécapitulatif final
Total HT : 1 000,00 EUR
TVA 20 % : 200,00 EUR
Net à payer : 1 200,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-multipage.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["fournisseur"], "Durand Maintenance")
        self.assertEqual(resultat["numero"], "DM-2026-104")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-22")
        self.assertEqual(resultat["montant_ht"], Decimal("1000.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("200.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("1200.00"))

    def test_extraction_francaise_distingue_total_ttc_et_solde_a_payer(self):
        contenu = """SARL DUPONT MAINTENANCE
12 rue des Ateliers 75001 Paris
SIRET : 123 456 789 00012
FACTURE N° FA-2026-0042    Date d'émission : 20/08/2026
Client : AXEREAL
Date d'échéance : 20/09/2026
\fTotal HT 1 000,00 EUR
TVA 20 % 200,00 EUR
Total TTC 1 200,00 EUR
Acompte déjà versé 200,00 EUR
Net à payer 1 000,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-francaise-acompte.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["montant_ht"], Decimal("1000.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("200.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("1200.00"))
        self.assertNotIn(
            "Montants comptables incohérents",
            resultat["_detection"]["alertes"],
        )

    def test_extraction_francaise_lit_les_champs_sur_une_meme_ligne(self):
        contenu = """ETABLISSEMENTS MARTIN SAS
SIREN : 123 456 789
FACTURE N° 20260042 | Date de facture : 21/08/2026 | Page 1/1
Facturé à : AXEREAL SILO
\fTOTAL HT 800,00 EUR | TVA 20 % 160,00 EUR | TOTAL TTC 960,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-francaise-champs-alignes.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "20260042")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-21")
        self.assertEqual(resultat["montant_ht"], Decimal("800.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("160.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("960.00"))

    def test_extraction_francaise_exclut_le_bloc_client_du_fournisseur(self):
        contenu = """FACTURE
Facturé à : AXEREAL SERVICES SAS
Adresse de facturation : 36 rue de la République
DUPONT ÉLECTROMÉCANIQUE SAS
SIRET : 123 456 789 00012
contact@dupont-electromecanique.fr
N° de facture : DE-2026-81
Date d'émission : 22/08/2026
\fTotal HT : 500,00 EUR
TVA 20 % : 100,00 EUR
Total TTC : 600,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-francaise-bloc-client.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["fournisseur"],
                         "DUPONT ÉLECTROMÉCANIQUE SAS")

    def test_extraction_francaise_identifie_les_blocs_emetteur_et_destinataire(self):
        contenu = """FACTURE
FACTURÉ À
AXEREAL SERVICES SAS
36 rue de la République
DUPONT ÉLECTROMÉCANIQUE SAS
SIRET : 123 456 789 00012
TVA intracommunautaire : FR00123456789
N° : 20260081
Date d'établissement : 22/08/2026
\fTotal HT : 500,00 EUR
TVA 20 % : 100,00 EUR
Total TTC : 600,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-francaise-blocs.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["fournisseur"],
                         "DUPONT ÉLECTROMÉCANIQUE SAS")
        self.assertEqual(resultat["numero"], "20260081")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-22")

    def test_extraction_francaise_lit_le_tableau_de_ventilation_tva(self):
        contenu = """ATELIERS MARTIN SARL
Facture N° AM-2026-19
Date de facture : 22/08/2026
\fBase HT       Taux TVA       Montant TVA
1 000,00 EUR    20,00 %        200,00 EUR
Total TTC : 1 200,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-francaise-ventilation-tva.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["montant_ht"], Decimal("1000.00"))
        self.assertEqual(resultat["taux_tva"], Decimal("20.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("200.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("1200.00"))

    def test_extraction_facture_guerineau_ne_confond_pas_client_et_tva(self):
        contenu = """L'ALGERIE                                      GUERINEAU Truck Service
49150 BAUGE EN ANJOU
06 71 30 95 68
guerineautruckservice@outlook.com
                                             SA ANJOU NEGOCE
                                             16 BOULEVARD DE LA GARE
                                             49490 NOYANT
                                             N° TVA Intracom : FR74389820937
Facture
Numéro             Date             Code client
FV002050            28/07/2026       411ANJ002
\fTotal HT 2 812,26 EUR
TVA 0,00 EUR
Total TTC 3 374,71 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-guerineau.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "FV002050")
        self.assertEqual(resultat["fournisseur"], "GUERINEAU Truck Service")
        self.assertEqual(str(resultat["date_facture"]), "2026-07-28")
        self.assertEqual(resultat["montant_ht"], Decimal("2812.26"))
        self.assertEqual(resultat["montant_tva"], Decimal("562.45"))
        self.assertEqual(resultat["taux_tva"], Decimal("20.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("3374.71"))
        self.assertNotIn(
            "Montants comptables incohérents",
            resultat["_detection"]["alertes"],
        )

    def test_extraction_calloux_detecte_description_et_vehicule(self):
        contenu = """CALLOUX
Facture
Numéro F-2026-08-4
Date d’émission 03 août 2026
Date d’échéance 15 août 2026
Émetteur ou Émettrice
CALLOUX
Client ou Cliente
AGRI NEGOCE SAS
Location Man TGX 470 immatriculé GT 111 AD du 26 juin au 30 juillet 2026
\fTotal HT 2 800,00 €
Total TVA 560,00 €
Total TTC 3 360,00 €
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-calloux.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "F-2026-08-4")
        self.assertEqual(resultat["fournisseur"], "CALLOUX")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-03")
        self.assertEqual(resultat["montant_ttc"], Decimal("3360.00"))
        self.assertIn("Location Man TGX 470", resultat["description_detectee"])
        self.assertEqual(
            resultat["vehicule_detecte"]["immatriculation"],
            "GT-111-AD",
        )

    def test_extraction_facture_guerineau_lit_le_recapitulatif_reel(self):
        contenu = """L'AIGLERIE
Facture
Numéro                  Date              Code client           N° TVA Intracom : FR74389820937
FV002050                 28/07/2026        411ANJ002
\fTaux         Base HT            Mont. TVA                   Récapitulatif                Mt net HT             Total HT 2 732,26
20,00        2 812,26              562,45                     Pièces                      1 811,43                Port HT 80,00
Facture à régler comptant                                  Main d'oeuvre                 627,00                  Total HT Net 2 812,26
Total TVA 562,45
Net à payer 3 374,71 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-guerineau-recapitulatif.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "FV002050")
        self.assertEqual(resultat["montant_ht"], Decimal("2812.26"))
        self.assertEqual(resultat["montant_tva"], Decimal("562.45"))
        self.assertEqual(resultat["taux_tva"], Decimal("20.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("3374.71"))

    def test_pdf_hybride_complete_le_texte_natif_insuffisant_par_ocr(self):
        class FakePage:
            def extract_text(self, **kwargs):
                return "LOGO FOURNISSEUR"

        class FakeReader:
            def __init__(self):
                self.pages = [FakePage()]

        ocr_text = """ATELIER DURAND SAS
Facture N° AD-9087
Date de facture : 20/08/2026
Total HT : 900,00 EUR
TVA 20 % : 180,00 EUR
Total TTC : 1 080,00 EUR
"""
        fichier = io.BytesIO(b"%PDF-1.4 hybride")
        fichier.name = "facture-hybride.pdf"

        with patch("maintenance.facture_extraction.PdfReader", return_value=FakeReader()), \
                patch("maintenance.facture_extraction.convert_from_bytes", return_value=[object()]) as convert, \
                patch("maintenance.facture_extraction._preprocess_image", side_effect=lambda image: image), \
                patch("maintenance.facture_extraction.pytesseract") as tesseract:
            tesseract.image_to_string.return_value = ocr_text
            resultat = extract_invoice_data_from_document(fichier)

        convert.assert_called_once()
        self.assertEqual(resultat["numero"], "AD-9087")
        self.assertEqual(resultat["montant_ttc"], Decimal("1080.00"))
        self.assertEqual(resultat["_detection"]["methode"], "pdf_texte_et_ocr")

    def test_pdf_ocr_cible_la_derniere_page_pour_les_totaux(self):
        class FakePage:
            def __init__(self, text):
                self.text = text

            def extract_text(self, **kwargs):
                return self.text

        class FakeReader:
            def __init__(self):
                self.pages = [
                    FakePage("""DURAND MAINTENANCE SAS
Facture N° DM-2026-105
Date de facture : 22/08/2026
Adresse : 12 rue des Ateliers
SIRET : 123 456 789 00012
"""),
                    FakePage("PAGE FINALE SCANNÉE"),
                ]

        totals_ocr = """Total HT : 2 000,00 EUR
TVA 20 % : 400,00 EUR
Net à payer : 2 400,00 EUR
"""
        fichier = io.BytesIO(b"%PDF-1.4 deux pages")
        fichier.name = "facture-derniere-page-scannee.pdf"

        with patch("maintenance.facture_extraction.PdfReader", return_value=FakeReader()), \
                patch("maintenance.facture_extraction.convert_from_bytes", return_value=[object()]) as convert, \
                patch("maintenance.facture_extraction._preprocess_image", side_effect=lambda image: image), \
                patch("maintenance.facture_extraction.pytesseract") as tesseract:
            tesseract.image_to_string.return_value = totals_ocr
            resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(convert.call_args.kwargs["first_page"], 2)
        self.assertEqual(convert.call_args.kwargs["last_page"], 2)
        self.assertEqual(resultat["numero"], "DM-2026-105")
        self.assertEqual(resultat["montant_ttc"], Decimal("2400.00"))

    def test_ocr_image_choisit_la_lecture_la_plus_riche(self):
        def ocr_data(lines):
            data = {
                "text": [], "conf": [], "block_num": [],
                "par_num": [], "line_num": [], "left": [],
            }
            for line_number, line in enumerate(lines, start=1):
                for word_number, word in enumerate(line.split(), start=1):
                    data["text"].append(word)
                    data["conf"].append("90")
                    data["block_num"].append(1)
                    data["par_num"].append(1)
                    data["line_num"].append(line_number)
                    data["left"].append(word_number * 100)
            return data

        sparse = ocr_data(["LOGO"])
        rich = ocr_data([
            "ATELIER DURAND SAS",
            "Facture AD-9090",
            "Date facture 21/08/2026",
            "Total HT 100,00 EUR",
            "TVA 20 % 20,00 EUR",
            "Total TTC 120,00 EUR",
        ])
        fichier = io.BytesIO(b"image simulee")
        fichier.name = "facture-scan.png"

        with patch("maintenance.facture_extraction.Image.open", return_value=object()), \
                patch("maintenance.facture_extraction._preprocess_image", side_effect=lambda image: image), \
                patch("maintenance.facture_extraction.pytesseract") as tesseract:
            tesseract.image_to_data.side_effect = [sparse, rich]
            resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(tesseract.image_to_data.call_count, 2)
        self.assertEqual(resultat["numero"], "AD-9090")
        self.assertEqual(resultat["montant_ttc"], Decimal("120.00"))
        self.assertEqual(resultat["_detection"]["methode"], "ocr_image")

    def test_ocr_image_priorise_le_fournisseur_en_haut_a_gauche(self):
        lines = [
            (1, 800, "AXEREAL SERVICES SAS"),
            (2, 10, "DURAND MAINTENANCE SAS"),
            (3, 100, "Facture DM-2026-106"),
            (4, 150, "Date facture 22/08/2026"),
            (5, 900, "Total HT 100,00 EUR"),
            (6, 950, "TVA 20 % 20,00 EUR"),
            (7, 1000, "Total TTC 120,00 EUR"),
        ]
        data = {
            "text": [], "conf": [], "block_num": [], "par_num": [],
            "line_num": [], "left": [], "top": [],
        }
        for block, top, line in lines:
            for word_number, word in enumerate(line.split(), start=1):
                data["text"].append(word)
                data["conf"].append("90")
                data["block_num"].append(block)
                data["par_num"].append(1)
                data["line_num"].append(1)
                data["left"].append(word_number * 100)
                data["top"].append(top)

        fichier = io.BytesIO(b"image simulee")
        fichier.name = "facture-positionnee.png"
        with patch("maintenance.facture_extraction.Image.open", return_value=object()), \
                patch("maintenance.facture_extraction._preprocess_image", side_effect=lambda image: image), \
                patch("maintenance.facture_extraction.pytesseract") as tesseract:
            tesseract.image_to_data.return_value = data
            resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["fournisseur"], "DURAND MAINTENANCE SAS")

    def test_extraction_fournisseur_depuis_email_explicitement_libelle(self):
        contenu = """Fournisseur : facturation.durand-maintenance@gmail.com
Facture N° DM-2026-107
Date de facture : 22/08/2026
Total HT : 100,00 EUR
TVA 20 % : 20,00 EUR
Total TTC : 120,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "facture-email.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["fournisseur"], "Durand Maintenance")

    def test_extraction_accepte_date_point_et_montants_negatifs_avoir(self):
        contenu = """ATELIER DURAND SAS
Avoir N° AV-2026-19
Date de facture : 20.08.2026
Total HT : -100,00 EUR
TVA 20 % : -20,00 EUR
Total TTC : -120,00 EUR
"""
        fichier = io.BytesIO(contenu.encode("utf-8"))
        fichier.name = "avoir.txt"

        resultat = extract_invoice_data_from_document(fichier)

        self.assertEqual(resultat["numero"], "AV-2026-19")
        self.assertEqual(str(resultat["date_facture"]), "2026-08-20")
        self.assertEqual(resultat["montant_ht"], Decimal("-100.00"))
        self.assertEqual(resultat["montant_tva"], Decimal("-20.00"))
        self.assertEqual(resultat["montant_ttc"], Decimal("-120.00"))

    def test_formulaire_accepte_les_totaux_negatifs_coherents(self):
        form = FactureForm(data={
            "panne": self._panne().pk,
            "numero": "AV-2026-20",
            "fournisseur": "ATELIER DURAND SAS",
            "montant_ht": "-100.00",
            "montant_tva": "-20.00",
            "montant_ttc": "-120.00",
            "taux_tva": "20.00",
        }, user=self.admin)

        self.assertTrue(form.is_valid(), form.errors)

    def test_creation_generale_detecte_conserve_fichier_et_lie_panne(self):
        panne = self._panne()
        self.client.login(username="admin_t", password="testpass123")
        fichier = io.BytesIO(b"%PDF-1.4\n")
        fichier.name = "facture-globale.pdf"
        with patch("maintenance.forms.extract_invoice_data_from_document", return_value={
            "numero": "FAC-GLOBALE-26",
            "fournisseur": "Prestataire Détecté",
            "date_facture": "2026-08-22",
            "montant_ht": "100.00",
            "montant_tva": "20.00",
            "taux_tva": "20.00",
            "montant_ttc": "120.00",
        }):
            response = self.client.post(
                reverse("facture_create"),
                {"panne": panne.pk, "fichier_upload": fichier},
                format="multipart",
            )

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.get(numero="FAC-GLOBALE-26")
        self.assertEqual(facture.panne, panne)
        self.assertTrue(facture.fichier)
        self.assertEqual(facture.nom_fichier_original, "facture-globale.pdf")
        self.assertEqual(facture.statut_detection, Facture.DETECTION_OK)
        self.assertEqual(facture.montant_ht, Decimal("100.00"))
        self.assertEqual(facture.montant_tva, Decimal("20.00"))

    def test_creation_generale_refuse_facture_sans_panne(self):
        self.client.login(username="admin_t", password="testpass123")
        response = self.client.post(
            reverse("facture_create"),
            {"numero": "SANS-PANNE", "fournisseur": "Test"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Chaque facture doit être reliée à une panne")
        self.assertFalse(Facture.objects.filter(numero="SANS-PANNE").exists())

    def test_ajouter_facture_coherente(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')
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
        facture = Facture.objects.get(panne=panne)
        self.assertEqual(facture.created_by, self.admin)

    def test_ajouter_facture_detecte_automatiquement_avec_pdf(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')
        fichier = io.BytesIO(b"%PDF-1.4\n")
        fichier.name = "facture-demo.pdf"
        with patch("maintenance.forms.extract_invoice_data_from_document", return_value={
            "numero": "FAC-AUTO-77",
            "fournisseur": "Fournisseur Auto",
            "date_facture": "2024-03-15",
            "montant_ttc": "456.78",
        }):
            response = self.client.post(
                reverse("panne_ajouter_facture", args=[panne.pk]),
                {
                    "numero": "",
                    "fournisseur": "",
                    "date_facture": "",
                    "montant_ht": "",
                    "montant_ttc": "",
                    "fichier_upload": fichier,
                },
                format="multipart",
            )
        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.get(panne=panne)
        self.assertEqual(facture.numero, "FAC-AUTO-77")
        self.assertEqual(facture.fournisseur, "Fournisseur Auto")
        self.assertEqual(str(facture.date_facture), "2024-03-15")
        self.assertEqual(str(facture.montant_ttc), "456.78")

    def test_ajouter_facture_minimale_sans_formulaire_complet(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')
        fichier = io.BytesIO(b"%PDF-1.4\n")
        fichier.name = "facture-minimale.pdf"
        with patch("maintenance.forms.extract_invoice_data_from_document", return_value={}):
            response = self.client.post(
                reverse("panne_ajouter_facture", args=[panne.pk]),
                {
                    "numero": "",
                    "fournisseur": "",
                    "date_facture": "",
                    "montant_ht": "",
                    "montant_ttc": "",
                    "fichier_upload": fichier,
                },
                format="multipart",
            )
        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.get(panne=panne)
        self.assertTrue(facture.numero.startswith("AUTO-"))
        self.assertEqual(facture.fournisseur, "À compléter")
        self.assertEqual(facture.montant_ttc, Decimal("0.00"))

    def test_temps_intervention_est_calculable(self):
        panne = self._panne()
        self.maintenance.profile.tarif_horaire = Decimal("85.00")
        self.maintenance.profile.save(update_fields=['tarif_horaire'])
        temps = panne.temps_interventions.create(
            agent=self.maintenance,
            duree_minutes=90,
            commentaire="Intervention de test",
            validee=True,
        )
        self.assertEqual(temps.montant, Decimal("127.50"))
        self.assertEqual(panne.total_temps_minutes, 90)
        self.assertEqual(panne.cout_total_intervention, Decimal("127.50"))

    def test_maintenance_ne_voit_pas_les_factures_de_la_panne(self):
        panne = self._panne()
        panne.affecte_a = self.maintenance
        panne.save(update_fields=["affecte_a"])
        Facture.objects.create(
            panne=panne,
            numero="FAC-MASQUEE",
            fournisseur="Fourni SA",
            montant_ht="100.00",
            montant_ttc="120.00",
        )
        self.client.login(username="maint_t", password='testpass123')
        response = self.client.get(reverse("panne_detail", args=[panne.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Factures")
        self.assertNotContains(response, "FAC-MASQUEE")

    def test_fichier_facture_telechargeable_uniquement_par_admin(self):
        panne = self._panne()
        facture = Facture.objects.create(
            panne=panne,
            numero="FAC-FICHIER-PRIVE",
            fournisseur="Fourni SA",
            montant_ht="100.00",
            montant_ttc="120.00",
            fichier=SimpleUploadedFile(
                "facture-privee.pdf", b"%PDF-1.4\nprivate"),
        )

        for username in ("maint_t", "silo_t"):
            with self.subTest(username=username):
                self.client.login(username=username, password='testpass123')
                response = self.client.get(
                    reverse("facture_telecharger", args=[facture.pk]))
                self.assertEqual(response.status_code, 403)

        self.assertFalse(
            Path(facture.fichier.path).is_relative_to(
                Path(settings.MEDIA_ROOT))
        )
        with self.assertRaises(ValueError):
            facture.fichier.url

        self.client.login(username="admin_t", password='testpass123')
        response = self.client.get(
            reverse("facture_telecharger", args=[facture.pk]))
        self.assertEqual(response.status_code, 200)

    def test_maintenance_ne_peut_pas_ajouter_facture(self):
        panne = self._panne()
        self.client.login(username="maint_t", password='testpass123')
        response = self.client.post(
            reverse("panne_ajouter_facture", args=[panne.pk]),
            {
                "numero": "FAC-INTERDITE",
                "fournisseur": "Fourni SA",
                "montant_ht": "100.00",
                "montant_ttc": "120.00",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Facture.objects.filter(
            numero="FAC-INTERDITE").exists())

    def test_maintenance_ne_peut_pas_modifier_facture(self):
        panne = self._panne()
        facture = Facture.objects.create(
            panne=panne,
            numero="FAC-ADMIN",
            fournisseur="Fourni SA",
            montant_ht="100.00",
            montant_ttc="120.00",
        )
        self.client.login(username="maint_t", password='testpass123')
        response = self.client.get(reverse(
            "panne_modifier_facture", args=[panne.pk, facture.pk]))
        self.assertEqual(response.status_code, 403)
        for route_name, args in (
            ("panne_ajouter_factures", [panne.pk]),
            ("panne_valider_facture", [panne.pk, facture.pk]),
            ("panne_supprimer_facture", [panne.pk, facture.pk]),
        ):
            with self.subTest(route_name=route_name):
                response = self.client.post(reverse(route_name, args=args))
                self.assertEqual(response.status_code, 403)
        facture.refresh_from_db()
        self.assertEqual(facture.statut, Facture.STATUT_BROUILLON)

    def test_facture_incoherente_ttc_inferieur_ht(self):
        panne = self._panne()
        self.client.login(username="admin_t", password='testpass123')
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

    def test_admin_valide_facture_de_la_panne(self):
        panne = self._panne()
        facture = Facture.objects.create(
            panne=panne,
            numero="FAC-VAL",
            fournisseur="Fourni SA",
            montant_ht="100.00",
            montant_ttc="120.00",
        )
        self.client.login(username="admin_t", password='testpass123')
        response = self.client.post(reverse(
            "panne_valider_facture", args=[panne.pk, facture.pk]))
        facture.refresh_from_db()
        self.assertRedirects(response, reverse(
            "panne_detail", args=[panne.pk]))
        self.assertEqual(facture.statut, Facture.STATUT_VALIDE)
        self.assertTrue(facture.validee)

    def test_facture_autre_panne_introuvable(self):
        panne = self._panne()
        autre_panne = Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Autre panne",
            description="Test",
        )
        facture = Facture.objects.create(
            panne=autre_panne,
            numero="FAC-AUTRE",
            fournisseur="Fourni SA",
            montant_ht="100.00",
            montant_ttc="120.00",
        )
        self.client.login(username="admin_t", password='testpass123')
        response = self.client.post(reverse(
            "panne_supprimer_facture", args=[panne.pk, facture.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Facture.objects.filter(pk=facture.pk).exists())


# ===========================================================================
# Smoke tests de toutes les vues GET
# ===========================================================================

class ViewsSmokeTests(SetupMixin):
    def setUp(self):
        super().setUp()
        self.panne = Panne.objects.create(
            site=self.site1,
            equipement=self.eq1,
            declarant=self.silo,
            titre="Panne smoke",
            description="Test des vues",
        )
        self.preventive = MaintenancePreventive.objects.create(
            site=self.site1,
            equipement=self.eq1,
            createur=self.admin,
            destinataire=self.silo,
            titre="Préventive smoke",
            instructions="Contrôler",
            echeance=timezone.now() + timedelta(days=7),
        )
        self.facture = Facture.objects.create(
            panne=self.panne,
            numero="FAC-SMOKE",
            fournisseur="Fournisseur smoke",
            montant_ht="100.00",
            montant_ttc="120.00",
            created_by=self.admin,
        )
        self.media = PanneMedia.objects.create(
            panne=self.panne,
            fichier="pannes/smoke.txt",
            nom_original="smoke.txt",
            ajoute_par=self.admin,
        )

    def test_toutes_les_vues_get_administrateur(self):
        self.client.login(username="admin_t", password='testpass123')
        routes = [
            ("dashboard", []),
            ("site_list", []),
            ("site_create", []),
            ("site_update", [self.site1.pk]),
            ("site_delete", [self.site1.pk]),
            ("equipement_list", []),
            ("equipement_create", []),
            ("equipement_update", [self.eq1.pk]),
            ("equipement_delete", [self.eq1.pk]),
            ("panne_liste", []),
            ("panne_creer", []),
            ("panne_detail", [self.panne.pk]),
            ("panne_delete", [self.panne.pk]),
            ("panne_media_delete", [self.media.pk]),
            ("panne_report", []),
            ("preventive_liste", []),
            ("preventive_creer", []),
            ("preventive_detail", [self.preventive.pk]),
            ("preventive_update", [self.preventive.pk]),
            ("facture_list", []),
            ("facture_create", []),
            ("facture_detail", [self.facture.pk]),
            ("facture_update", [self.facture.pk]),
            ("facture_delete", [self.facture.pk]),
            ("facture_file_delete", [self.facture.pk]),
            ("report_selector", []),
            ("period_report", []),
            ("site_report", []),
            ("site_report_detail", [self.site1.pk]),
            ("monthly_report", [2030, 1]),
            ("utilisateur_list", []),
            ("utilisateur_create", []),
            ("utilisateur_update", [self.admin.pk]),
            ("mon_profil", []),
            ("notification_liste", []),
        ]
        for route_name, args in routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name, args=args))
                self.assertEqual(response.status_code, 200)

    def test_suppression_site_liee_a_historique_est_refusee_sans_crash(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(
            reverse("site_delete", args=[self.site1.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("site_list"))
        self.assertContains(
            response,
            "Ce site ne peut pas être supprimé car il est lié à des "
            "équipements ou à un historique de maintenance.",
        )
        self.assertTrue(Site.objects.filter(pk=self.site1.pk).exists())

    def test_suppression_site_sans_historique_reussit(self):
        site = Site.objects.create(nom="Site à supprimer")
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("site_delete", args=[site.pk]))

        self.assertRedirects(response, reverse("site_list"))
        self.assertFalse(Site.objects.filter(pk=site.pk).exists())

    def test_navigation_admin_reste_complete_sur_toutes_les_pages(self):
        self.client.login(username="admin_t", password='testpass123')
        routes = (
            ("site_list", []),
            ("facture_detail", [self.facture.pk]),
            ("preventive_detail", [self.preventive.pk]),
            ("panne_delete", [self.panne.pk]),
        )

        for route_name, args in routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Préventives")
                self.assertContains(response, "Équipements")
                self.assertContains(response, "Gestion")
                self.assertContains(response, "Utilisateurs")
                self.assertNotContains(response, 'href="/admin/"')

    def test_administrateur_metier_cree_un_site_avec_photo(self):
        self.client.login(username="admin_t", password="testpass123")

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse("site_create"), {
                "nom": "Site avec photo",
                "adresse": "Adresse test",
                "actif": "on",
                "photos": _png_file("site.png"),
            })

            site = Site.objects.get(nom="Site avec photo")
            photo = SitePhoto.objects.get(site=site)
            self.assertRedirects(response, reverse("site_list"))

            liste = self.client.get(reverse("site_list"))
            self.assertContains(
                liste,
                reverse("site_photo_afficher", args=[photo.pk]),
            )

            self.client.login(username="silo_t", password="testpass123")
            self.assertEqual(
                self.client.get(
                    reverse("site_photo_afficher", args=[photo.pk])
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.post(
                    reverse("site_photo_delete", args=[photo.pk])
                ).status_code,
                403,
            )

    def test_formulaires_preventifs_get(self):
        self.client.login(username="silo_t", password='testpass123')
        self.preventive.statut = MaintenancePreventive.Statut.EN_COURS
        self.preventive.save(update_fields=["statut"])
        response = self.client.get(reverse(
            "preventive_terminer", args=[self.preventive.pk]))
        self.assertEqual(response.status_code, 200)

        self.client.login(username="admin_t", password='testpass123')
        self.preventive.statut = MaintenancePreventive.Statut.A_VALIDER
        self.preventive.save(update_fields=["statut"])
        response = self.client.get(reverse(
            "preventive_valider", args=[self.preventive.pk]))
        self.assertEqual(response.status_code, 200)

    def test_exports_pdf(self):
        self.client.login(username="admin_t", password='testpass123')
        for route_name, args in (
            ("period_report", []),
            ("site_report", []),
            ("site_report_detail", [self.site1.pk]),
            ("monthly_report", [2030, 1]),
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(route_name, args=args), {"format": "pdf"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")

    def test_selecteur_rapport_redirige_vers_la_periode_choisie(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("report_selector"), {
            "start_date": "2026-06-15",
            "end_date": "2026-08-20",
            "site": self.site1.pk,
        })

        self.assertRedirects(
            response,
            f'{reverse("period_report")}?start_date=2026-06-15&end_date=2026-08-20&site={self.site1.pk}',
            fetch_redirect_response=False,
        )

    def test_vues_rapport_sont_interconnectees(self):
        self.client.login(username="admin_t", password="testpass123")
        today = timezone.localdate()

        selector = self.client.get(reverse("report_selector"))
        self.assertContains(selector, reverse("site_report"))
        self.assertContains(
            selector,
            reverse("monthly_report", args=[today.year, today.month]),
        )

        sites_report = self.client.get(reverse("site_report"))
        self.assertContains(sites_report, reverse("report_selector"))
        self.assertContains(
            sites_report,
            reverse("site_report_detail", args=[self.site1.pk]),
        )

        monthly_report = self.client.get(
            reverse("monthly_report", args=[today.year, today.month])
        )
        self.assertContains(monthly_report, reverse("report_selector"))

    def test_rapport_periode_filtre_avec_bornes_inclusives(self):
        self.client.login(username="admin_t", password="testpass123")
        self.panne.statut = Panne.STATUT_TERMINEE
        self.panne.date_resolution = datetime(
            2026, 7, 10, 12, 0, tzinfo=timezone.get_current_timezone()
        )
        self.panne.save(update_fields=["statut", "date_resolution"])
        panne_hors_periode = Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Panne hors période",
            description="Ne doit pas être comptée",
            statut=Panne.STATUT_TERMINEE,
            date_resolution=datetime(
                2026, 8, 21, 12, 0,
                tzinfo=timezone.get_current_timezone(),
            ),
        )
        Facture.objects.create(
            panne=panne_hors_periode,
            numero="FAC-HORS-PERIODE",
            fournisseur="Fournisseur hors période",
            montant_ht="500.00",
            montant_ttc="600.00",
            created_by=self.admin,
        )

        response = self.client.get(reverse("period_report"), {
            "start_date": "2026-07-10",
            "end_date": "2026-08-20",
            "site": self.site1.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period_start"], date(2026, 7, 10))
        self.assertEqual(response.context["period_end"], date(2026, 8, 20))
        self.assertEqual(response.context["sites_data"][0]["panne_count"], 1)
        self.assertContains(response, "Du 10/07/2026 au 20/08/2026")

    def test_crud_principaux(self):
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(reverse("site_create"), {
            "nom": "Site créé par la vue",
            "adresse": "Adresse test",
            "actif": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Site.objects.filter(
            nom="Site créé par la vue").exists())

        response = self.client.post(reverse("equipement_create"), {
            "site": self.site1.pk,
            "nom": "Équipement créé par la vue",
            "reference": "EQ-VUE",
            "actif": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Equipement.objects.filter(reference="EQ-VUE").exists())

        response = self.client.post(reverse("preventive_update", args=[self.preventive.pk]), {
            "site": self.site1.pk,
            "equipement": self.eq1.pk,
            "affecte_a": self.silo.pk,
            "titre": "Préventive modifiée",
            "description": "Description modifiée",
            "date_echeance": "2030-01-01T10:00",
        })
        self.assertEqual(response.status_code, 302)
        self.preventive.refresh_from_db()
        self.assertEqual(self.preventive.titre, "Préventive modifiée")

        response = self.client.post(reverse("facture_create"), {
            "panne": self.panne.pk,
            "preventive": "",
            "numero": "FAC-CREATE-VIEW",
            "fournisseur": "Fournisseur vue",
            "type_facture": Facture.TYPE_AUTRE,
            "statut": Facture.STATUT_BROUILLON,
            "montant_ht": "50.00",
            "taux_tva": "20.00",
            "montant_tva": "10.00",
            "montant_ttc": "60.00",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Facture.objects.filter(
            numero="FAC-CREATE-VIEW").exists())

        response = self.client.post(reverse("utilisateur_create"), {
            "username": "utilisateur_vue",
            "first_name": "Utilisateur",
            "last_name": "Vue",
            "email": "vue@example.com",
            "password": "testpass123",
            "role": Profile.Role.SILO,
            "sites_autorises": [self.site1.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(
            username="utilisateur_vue").exists())


# ===========================================================================
# Tests de gestion des utilisateurs
# ===========================================================================

class UtilisateurTests(SetupMixin):
    def test_agent_silo_doit_avoir_au_moins_un_site(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("utilisateur_create"), {
            "username": "silo_sans_site_t",
            "password": "motdepasse-initial",
            "role": Profile.Role.SILO,
            "tarif_horaire": "0",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Affectez au moins un site à cet agent de silo.",
        )
        self.assertFalse(User.objects.filter(
            username="silo_sans_site_t").exists())

    def test_admin_affecte_plusieurs_sites_a_un_agent_silo(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(reverse("utilisateur_create"), {
            "username": "silo_multisites_t",
            "password": "motdepasse-initial",
            "role": Profile.Role.SILO,
            "sites_autorises": [self.site1.pk, self.site2.pk],
            "tarif_horaire": "0",
        })

        self.assertRedirects(response, reverse("utilisateur_list"))
        utilisateur = User.objects.get(username="silo_multisites_t")
        self.assertSetEqual(
            set(utilisateur.sites_autorises.all()),
            {self.site1, self.site2},
        )

    def test_admin_ne_peut_pas_retirer_tous_les_sites_agent_silo(self):
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.post(
            reverse("utilisateur_update", args=[self.silo.pk]),
            {
                "username": self.silo.username,
                "role": Profile.Role.SILO,
                "tarif_horaire": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Affectez au moins un site à cet agent de silo.",
        )
        self.assertSetEqual(
            set(self.silo.sites_autorises.all()),
            {self.site1},
        )

    def test_admin_ne_peut_pas_dupliquer_une_adresse_email(self):
        self.maintenance.email = "agent.unique@example.com"
        self.maintenance.save(update_fields=["email"])
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(reverse("utilisateur_create"), {
            "username": "email_duplique_t",
            "first_name": "Adresse",
            "last_name": "Dupliquée",
            "email": "AGENT.UNIQUE@example.com",
            "password": "motdepasse-initial",
            "role": Profile.Role.SILO,
            "tarif_horaire": "0",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Cette adresse e-mail est déjà utilisée.")
        self.assertFalse(User.objects.filter(
            username="email_duplique_t").exists())

    def test_administrateur_metier_n_est_pas_administrateur_django(self):
        self.client.login(username="admin_t", password="testpass123")
        response = self.client.post(reverse("utilisateur_create"), {
            "username": "admin_metier_t",
            "first_name": "Admin",
            "last_name": "Métier",
            "email": "admin-metier@example.com",
            "password": "testpass123",
            "role": Profile.Role.ADMIN,
            "tarif_horaire": "0",
        })

        self.assertRedirects(response, reverse("utilisateur_list"))
        administrateur = User.objects.get(username="admin_metier_t")
        self.assertTrue(administrateur.profile.is_admin())
        self.assertFalse(administrateur.is_staff)

        self.client.login(username="admin_metier_t", password="testpass123")
        for route_name in ("site_list", "equipement_list", "utilisateur_list"):
            with self.subTest(route_name=route_name):
                self.assertEqual(self.client.get(
                    reverse(route_name)).status_code, 200)
        self.assertNotEqual(self.client.get("/admin/").status_code, 200)

    def test_admin_cree_agent_maintenance_avec_tarif_horaire(self):
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(reverse("utilisateur_create"), {
            "username": "maintenance_tarif_t",
            "first_name": "Agent",
            "last_name": "Tarifé",
            "email": "agent@example.com",
            "password": "motdepasse-initial",
            "role": Profile.Role.MAINTENANCE,
            "tarif_horaire": "72.50",
        })

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="maintenance_tarif_t")
        self.assertEqual(user.profile.tarif_horaire, Decimal("72.50"))

    def test_admin_modifie_tarif_horaire_sans_modifier_mot_de_passe(self):
        ancien_mot_de_passe = self.maintenance.password
        self.client.login(username="admin_t", password='testpass123')

        detail = self.client.get(
            reverse("utilisateur_update", args=[self.maintenance.pk]))
        self.assertContains(detail, 'name="tarif_horaire"')
        self.assertNotContains(detail, 'name="password"')

        response = self.client.post(
            reverse("utilisateur_update", args=[self.maintenance.pk]),
            {
                "username": self.maintenance.username,
                "first_name": "Agent",
                "last_name": "Maintenance",
                "email": "maintenance@example.com",
                "role": Profile.Role.MAINTENANCE,
                "tarif_horaire": "95.00",
            },
        )

        self.maintenance.refresh_from_db()
        self.maintenance.profile.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.maintenance.password, ancien_mot_de_passe)
        self.assertTrue(self.maintenance.check_password('testpass123'))
        self.assertEqual(
            self.maintenance.profile.tarif_horaire, Decimal("95.00"))

    def test_admin_supprime_un_utilisateur_sans_historique(self):
        utilisateur = make_user("compte_a_supprimer", Profile.Role.SILO)
        self.client.login(username="admin_t", password='testpass123')

        confirmation = self.client.get(
            reverse("utilisateur_delete", args=[utilisateur.pk]))
        response = self.client.post(
            reverse("utilisateur_delete", args=[utilisateur.pk]))

        self.assertEqual(confirmation.status_code, 200)
        self.assertRedirects(response, reverse("utilisateur_list"))
        self.assertFalse(User.objects.filter(pk=utilisateur.pk).exists())

    def test_admin_ne_peut_pas_supprimer_son_propre_compte(self):
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_delete", args=[self.admin.pk]))

        self.assertRedirects(response, reverse("utilisateur_list"))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_admin_ne_peut_pas_supprimer_utilisateur_lie_a_historique(self):
        Panne.objects.create(
            site=self.site1,
            signale_par=self.silo,
            titre="Historique protégé",
            description="Panne conservée pour la traçabilité.",
        )
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_delete", args=[self.silo.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "historique de maintenance")
        self.assertTrue(User.objects.filter(pk=self.silo.pk).exists())

    def test_agent_silo_ne_peut_pas_supprimer_un_utilisateur(self):
        utilisateur = make_user("compte_protege", Profile.Role.SILO)
        self.client.login(username="silo_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_delete", args=[utilisateur.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=utilisateur.pk).exists())

    def test_admin_desactive_et_reactive_un_compte(self):
        utilisateur = make_user("compte_activation", Profile.Role.SILO)
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_changer_activation", args=[utilisateur.pk]),
            {"actif": "0"},
        )
        utilisateur.refresh_from_db()

        self.assertRedirects(response, reverse("utilisateur_list"))
        self.assertFalse(utilisateur.is_active)
        self.client.logout()
        self.assertFalse(self.client.login(
            username="compte_activation", password='testpass123'))

        self.client.login(username="admin_t", password='testpass123')
        response = self.client.post(
            reverse("utilisateur_changer_activation", args=[utilisateur.pk]),
            {"actif": "1"},
        )
        utilisateur.refresh_from_db()

        self.assertRedirects(response, reverse("utilisateur_list"))
        self.assertTrue(utilisateur.is_active)

    def test_admin_ne_peut_pas_desactiver_son_propre_compte(self):
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_changer_activation", args=[self.admin.pk]),
            {"actif": "0"},
        )
        self.admin.refresh_from_db()

        self.assertRedirects(response, reverse("utilisateur_list"))
        self.assertTrue(self.admin.is_active)

    def test_agent_silo_ne_peut_pas_desactiver_un_compte(self):
        utilisateur = make_user(
            "compte_activation_interdite", Profile.Role.SILO)
        self.client.login(username="silo_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_changer_activation", args=[utilisateur.pk]),
            {"actif": "0"},
        )
        utilisateur.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(utilisateur.is_active)

    def test_admin_peut_desactiver_un_compte_ancien_sans_profil(self):
        utilisateur = User.objects.create_user(
            username="compte_sans_profil",
            password='testpass123',
        )
        self.client.login(username="admin_t", password='testpass123')

        response = self.client.post(
            reverse("utilisateur_changer_activation", args=[utilisateur.pk]),
            {"actif": "0"},
        )
        utilisateur.refresh_from_db()

        self.assertRedirects(response, reverse("utilisateur_list"))
        self.assertFalse(utilisateur.is_active)


# ===========================================================================
# Tests des notifications
# ===========================================================================

class NotificationTests(SetupMixin):
    def test_liste_affiche_notifications_lues_et_non_lues_avec_compteur(self):
        Notification.objects.create(
            utilisateur=self.admin,
            titre="Notification non lue",
            message="À traiter",
            lue=False,
        )
        Notification.objects.create(
            utilisateur=self.admin,
            titre="Notification déjà lue",
            message="Historique",
            lue=True,
        )
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.get(reverse("notification_liste"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["non_lues"], 1)
        self.assertEqual(response.context["notifications_non_lues"], 1)
        self.assertEqual(len(response.context["notifications"]), 2)
        self.assertContains(response, "Notification non lue")
        self.assertContains(response, "Notification déjà lue")
        self.assertNotContains(response, "Aucune notification.")

    def test_dashboard_admin_alerte_seulement_si_panne_non_assignee(self):
        panne = Panne.objects.create(
            site=self.site1,
            signale_par=self.silo,
            titre="Panne à affecter",
            description="Une panne vient d'être déclarée.",
        )
        self.client.login(username="admin_t", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["notifications_non_lues"], 1)
        self.assertTrue(response.context["pannes_non_assignees"])
        self.assertContains(response, "bi-bell-fill")
        self.assertContains(response, "metric-card-alerting")

        panne.affecte_a = self.maintenance
        panne.statut = Panne.Statut.AFFECTEE
        panne.save(update_fields=["affecte_a", "statut"])

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["notifications_non_lues"], 1)
        self.assertFalse(response.context["pannes_non_assignees"])
        self.assertContains(response, "bi-exclamation-diamond")
        self.assertNotContains(response, "metric-card-alerting")

    @patch("maintenance.services._diffuser_ws")
    def test_notification_panne_est_diffusee_a_chaque_destinataire(self, diffuser):
        Panne.objects.create(
            site=self.site1,
            declarant=self.silo,
            titre="Diffusion ciblée",
            description="Desc",
            statut=Panne.Statut.NOUVELLE,
        )

        destinataires = {appel.args[0] for appel in diffuser.call_args_list}
        self.assertEqual(destinataires, {self.admin.pk, self.maintenance.pk})
        self.assertTrue(all(
            appel.args[1] == Notification.TypeNotif.PANNE_CREEE
            for appel in diffuser.call_args_list
        ))

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
        r = self.client.post(
            reverse("notification_marquer_lue", args=[notif.pk]))
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
        self.assertEqual(
            p.statut, MaintenancePreventive.Statut.ENVOYEE)  # inchangé


# ===========================================================================
# Tests de la commande seed_demo
# ===========================================================================

class SeedDemoTests(SetupMixin):
    def test_seed_demo_cree_donnees(self):
        call_command("seed_demo", verbosity=0)
        self.assertTrue(Site.objects.filter(nom="Silo Nord").exists())
        self.assertTrue(User.objects.filter(username="admin_demo").exists())
        silo_demo = User.objects.get(username="silo_demo")
        self.assertSetEqual(
            set(silo_demo.sites_autorises.filter(
                nom__in=["Silo Nord", "Silo Sud"]
            ).values_list("nom", flat=True)),
            {"Silo Nord", "Silo Sud"},
        )
