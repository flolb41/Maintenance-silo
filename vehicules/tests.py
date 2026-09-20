import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.timezone import localdate

from maintenance.models import Profile, Site

from .models import EntretienVehicule, Vehicule


User = get_user_model()


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PRIVATE_INVOICE_ROOT=tempfile.mkdtemp(),
)
class VehiculeWorkflowTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(nom="Site véhicules", actif=True)
        self.admin = User.objects.create_user(
            "admin_vehicules", password="testpass123")
        Profile.objects.create(user=self.admin, role=Profile.Role.ADMIN)
        self.silo = User.objects.create_user(
            "silo_vehicules", password="testpass123")
        Profile.objects.create(user=self.silo, role=Profile.Role.SILO)
        self.site.utilisateurs.add(self.silo)
        self.vehicule = Vehicule.objects.create(
            site=self.site,
            categorie=Vehicule.Categorie.POIDS_LOURD,
            immatriculation="PL-123-AA",
            marque="Renault Trucks",
            modele="T",
            kilometrage=120000,
            cree_par=self.admin,
        )

    def test_administrateur_accede_au_module_et_au_menu(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        liste = self.client.get(reverse("vehicules:liste"))

        self.assertEqual(liste.status_code, 200)
        self.assertContains(liste, "Véhicules")
        self.assertContains(liste, self.vehicule.immatriculation)
        self.assertContains(liste, reverse("vehicules:ajouter"))
        self.assertEqual(liste.context["total_engins"], 0)
        self.assertEqual(
            self.client.get(reverse("vehicules:detail", args=[
                            self.vehicule.pk])).status_code,
            200,
        )

    def test_agent_silo_ne_peut_pas_acceder_au_module(self):
        self.client.login(username="silo_vehicules", password="testpass123")

        for route in (
            reverse("vehicules:liste"),
            reverse("vehicules:ajouter"),
            reverse("vehicules:detail", args=[self.vehicule.pk]),
            reverse("vehicules:modifier", args=[self.vehicule.pk]),
            reverse("vehicules:supprimer", args=[self.vehicule.pk]),
        ):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 403)

    def test_administrateur_supprime_un_vehicule(self):
        self.client.login(username="admin_vehicules", password="testpass123")
        suppression_url = reverse(
            "vehicules:supprimer", args=[self.vehicule.pk]
        )

        liste = self.client.get(reverse("vehicules:liste"))
        confirmation = self.client.get(suppression_url)
        response = self.client.post(suppression_url)

        self.assertContains(liste, suppression_url)
        self.assertContains(confirmation, "Supprimer définitivement")
        self.assertRedirects(response, reverse("vehicules:liste"))
        self.assertFalse(Vehicule.objects.filter(pk=self.vehicule.pk).exists())

    def test_administrateur_ajoute_un_poids_lourd(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        response = self.client.post(reverse("vehicules:ajouter"), {
            "site": self.site.pk,
            "categorie": Vehicule.Categorie.POIDS_LOURD,
            "immatriculation": "pl-456-bb",
            "marque": "Peugeot",
            "modele": "Partner",
            "carburant": Vehicule.Carburant.DIESEL,
            "statut": Vehicule.Statut.DISPONIBLE,
            "kilometrage": 25000,
        })

        vehicule = Vehicule.objects.get(immatriculation="PL-456-BB")
        self.assertRedirects(response, reverse(
            "vehicules:detail", args=[vehicule.pk]))
        self.assertEqual(vehicule.cree_par, self.admin)
        self.assertEqual(vehicule.categorie, Vehicule.Categorie.POIDS_LOURD)

    def test_un_engin_de_manutention_exige_une_vgp(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        response = self.client.post(reverse("vehicules:ajouter"), {
            "site": self.site.pk,
            "categorie": Vehicule.Categorie.ENGIN_MANUTENTION,
            "immatriculation": "MAN-456-BB",
            "marque": "Manitou",
            "modele": "MT 625",
            "carburant": Vehicule.Carburant.DIESEL,
            "statut": Vehicule.Statut.DISPONIBLE,
            "kilometrage": 2500,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].errors["date_vgp"][0],
            "La date d'échéance VGP est obligatoire pour un engin de manutention.",
        )

        response = self.client.post(reverse("vehicules:ajouter"), {
            "site": self.site.pk,
            "categorie": Vehicule.Categorie.ENGIN_MANUTENTION,
            "immatriculation": "man-456-bb",
            "marque": "Manitou",
            "modele": "MT 625",
            "carburant": Vehicule.Carburant.DIESEL,
            "statut": Vehicule.Statut.DISPONIBLE,
            "kilometrage": 2500,
            "date_vgp": "2027-06-30",
            "organisme_vgp": "Autre organisme",
        })

        vehicule = Vehicule.objects.get(immatriculation="MAN-456-BB")
        self.assertRedirects(response, reverse(
            "vehicules:detail", args=[vehicule.pk]))
        self.assertEqual(vehicule.organisme_vgp, "DEKRA")

    def test_immatriculation_facultative_pour_un_engin(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        response = self.client.post(reverse("vehicules:ajouter"), {
            "site": self.site.pk,
            "categorie": Vehicule.Categorie.ENGIN_MANUTENTION,
            "marque": "Toyota",
            "modele": "8FG25",
            "carburant": Vehicule.Carburant.GAZ,
            "statut": Vehicule.Statut.DISPONIBLE,
            "kilometrage": 1800,
            "date_vgp": "2027-06-30",
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Vehicule.objects.filter(
            immatriculation="", categorie=Vehicule.Categorie.ENGIN_MANUTENTION
        ).exists())

    def test_immatriculation_obligatoire_pour_un_poids_lourd(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        response = self.client.post(reverse("vehicules:ajouter"), {
            "site": self.site.pk,
            "categorie": Vehicule.Categorie.POIDS_LOURD,
            "marque": "Volvo",
            "modele": "FH",
            "carburant": Vehicule.Carburant.DIESEL,
            "statut": Vehicule.Statut.DISPONIBLE,
            "kilometrage": 180000,
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("immatriculation", response.context["form"].errors)

    def test_remorque_exige_une_immatriculation_et_un_passage_aux_mines(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        donnees = {
            "site": self.site.pk,
            "categorie": Vehicule.Categorie.REMORQUE_POIDS_LOURD,
            "marque": "Schmitz",
            "modele": "S.KO",
            "carburant": Vehicule.Carburant.AUTRE,
            "statut": Vehicule.Statut.DISPONIBLE,
            "kilometrage": 0,
        }
        response = self.client.post(reverse("vehicules:ajouter"), donnees)

        self.assertEqual(response.status_code, 200)
        self.assertIn("immatriculation", response.context["form"].errors)
        self.assertIn("date_mines", response.context["form"].errors)

        donnees.update({
            "immatriculation": "TR-456-AA",
            "date_mines": "2027-06-30",
        })
        response = self.client.post(reverse("vehicules:ajouter"), donnees)

        remorque = Vehicule.objects.get(immatriculation="TR-456-AA")
        self.assertRedirects(response, reverse(
            "vehicules:detail", args=[remorque.pk]))
        self.assertEqual(remorque.categorie,
                         Vehicule.Categorie.REMORQUE_POIDS_LOURD)

    @patch("maintenance.models.optimiser_media_televerse")
    def test_photo_vehicule_est_optimisee(self, optimiser):
        optimiser.return_value = SimpleUploadedFile(
            "camion.webp",
            b"photo optimisee",
            content_type="image/webp",
        )

        self.vehicule.photo = SimpleUploadedFile(
            "camion.jpg",
            b"photo originale plus volumineuse",
            content_type="image/jpeg",
        )
        self.vehicule.save(update_fields=["photo"])

        self.assertTrue(self.vehicule.photo.name.endswith(".webp"))
        optimiser.assert_called_once()

    def test_entretien_met_a_jour_le_kilometrage_et_le_cout(self):
        self.client.login(username="admin_vehicules", password="testpass123")

        response = self.client.post(
            reverse("vehicules:entretien_ajouter", args=[self.vehicule.pk]),
            {
                "type_entretien": EntretienVehicule.TypeEntretien.REVISION,
                "date_entretien": localdate().isoformat(),
                "kilometrage": 125000,
                "prestataire": "Garage central",
                "description": "Révision complète",
                "cout": "850.50",
            },
        )

        self.assertRedirects(response, reverse(
            "vehicules:detail", args=[self.vehicule.pk]))
        self.vehicule.refresh_from_db()
        self.assertEqual(self.vehicule.kilometrage, 125000)
        entretien = self.vehicule.entretiens.get()
        self.assertEqual(entretien.cout, Decimal("850.50"))
        self.assertEqual(entretien.cree_par, self.admin)

    def test_facture_entretien_est_stockee_hors_des_medias_publics(self):
        entretien = EntretienVehicule.objects.create(
            vehicule=self.vehicule,
            type_entretien=EntretienVehicule.TypeEntretien.REVISION,
            date_entretien=localdate(),
            kilometrage=125000,
            description="Révision avec facture",
            facture=SimpleUploadedFile(
                "facture-entretien.pdf", b"%PDF-1.4\nprivate"
            ),
            cree_par=self.admin,
        )

        self.assertFalse(
            Path(entretien.facture.path).is_relative_to(
                Path(settings.MEDIA_ROOT))
        )
        with self.assertRaises(ValueError):
            entretien.facture.url

        self.client.login(username="silo_vehicules", password="testpass123")
        self.assertEqual(
            self.client.get(reverse(
                "vehicules:entretien_facture", args=[entretien.pk]
            )).status_code,
            403,
        )
        self.client.login(username="admin_vehicules", password="testpass123")
        self.assertEqual(
            self.client.get(reverse(
                "vehicules:entretien_facture", args=[entretien.pk]
            )).status_code,
            200,
        )

    def test_rapport_vgp_prive_est_telechargeable_par_admin(self):
        self.vehicule.date_vgp = localdate() + timedelta(days=90)
        self.vehicule.rapport_vgp = SimpleUploadedFile(
            "rapport-vgp.pdf", b"%PDF-1.4\nrapport prive"
        )
        self.vehicule.save(update_fields=["date_vgp", "rapport_vgp"])

        self.assertFalse(
            Path(self.vehicule.rapport_vgp.path).is_relative_to(
                Path(settings.MEDIA_ROOT)
            )
        )
        with self.assertRaises(ValueError):
            self.vehicule.rapport_vgp.url

        self.client.login(username="silo_vehicules", password="testpass123")
        self.assertEqual(
            self.client.get(reverse(
                "vehicules:rapport_vgp", args=[self.vehicule.pk]
            )).status_code,
            403,
        )
        self.client.login(username="admin_vehicules", password="testpass123")
        self.assertEqual(
            self.client.get(reverse(
                "vehicules:rapport_vgp", args=[self.vehicule.pk]
            )).status_code,
            200,
        )

    def test_echeance_dans_trente_jours_declenche_une_alerte(self):
        self.vehicule.date_assurance = localdate() + timedelta(days=15)
        self.vehicule.save(update_fields=["date_assurance"])

        self.assertTrue(self.vehicule.alerte_echeance)
