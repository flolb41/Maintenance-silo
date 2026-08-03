from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from decimal import Decimal
from datetime import date, timedelta

from .models import (
    Site, Profile, Equipement, Panne, MaintenancePreventive, Facture
)


def make_user(username, role, site=None):
    pw = 'Test@1234'
    user = User.objects.create_user(username=username, password=pw)
    profile = Profile.objects.create(user=user, role=role)
    if site:
        profile.sites.add(site)
    return user, pw


class ModelPanneTest(TestCase):
    def setUp(self):
        self.site = Site.objects.create(nom='Site A')
        self.eq = Equipement.objects.create(site=self.site, nom='Convoyeur', categorie='convoyeur')
        self.admin, _ = make_user('admin1', Profile.ROLE_ADMIN, self.site)

    def test_transition_autorisee(self):
        panne = Panne.objects.create(
            equipement=self.eq, titre='Test', description='desc',
            signale_par=self.admin, statut=Panne.STATUT_NOUVELLE
        )
        panne.changer_statut(Panne.STATUT_AFFECTEE, self.admin, 'commentaire')
        self.assertEqual(panne.statut, Panne.STATUT_AFFECTEE)
        self.assertEqual(panne.historique.count(), 1)

    def test_transition_interdite_leve_exception(self):
        panne = Panne.objects.create(
            equipement=self.eq, titre='Test', description='desc',
            signale_par=self.admin, statut=Panne.STATUT_NOUVELLE
        )
        with self.assertRaises(ValueError):
            panne.changer_statut(Panne.STATUT_RESOLUE, self.admin)

    def test_date_resolution_remplie_a_resolution(self):
        panne = Panne.objects.create(
            equipement=self.eq, titre='Test', description='desc',
            signale_par=self.admin, statut=Panne.STATUT_EN_COURS
        )
        panne.changer_statut(Panne.STATUT_RESOLUE, self.admin)
        self.assertIsNotNone(panne.date_resolution)


class ModelPreventiveTest(TestCase):
    def setUp(self):
        self.site = Site.objects.create(nom='Site B')
        self.eq = Equipement.objects.create(site=self.site, nom='Élévateur', categorie='elevateur')
        self.admin, _ = make_user('admin2', Profile.ROLE_ADMIN, self.site)

    def test_est_en_retard_vrai(self):
        pv = MaintenancePreventive.objects.create(
            equipement=self.eq,
            titre='Révision',
            description='desc',
            date_echeance=date.today() - timedelta(days=1),
            statut=MaintenancePreventive.STATUT_PLANIFIEE,
            created_by=self.admin,
        )
        self.assertTrue(pv.est_en_retard())

    def test_est_en_retard_faux_si_effectuee(self):
        pv = MaintenancePreventive.objects.create(
            equipement=self.eq,
            titre='Révision 2',
            description='desc',
            date_echeance=date.today() - timedelta(days=1),
            statut=MaintenancePreventive.STATUT_EFFECTUEE,
            created_by=self.admin,
        )
        self.assertFalse(pv.est_en_retard())


class ModelFactureTest(TestCase):
    def setUp(self):
        self.site = Site.objects.create(nom='Site C')
        self.eq = Equipement.objects.create(site=self.site, nom='Ventilateur', categorie='ventilateur')
        self.user, _ = make_user('maint1', Profile.ROLE_MAINTENANCE, self.site)
        self.panne = Panne.objects.create(
            equipement=self.eq, titre='Panne test', description='x',
            signale_par=self.user
        )

    def test_facture_coherente(self):
        f = Facture(
            panne=self.panne,
            numero='FACT-001',
            fournisseur='Test',
            montant_ht=Decimal('100.00'),
            montant_tva=Decimal('20.00'),
            montant_ttc=Decimal('120.00'),
            date_facture=date.today(),
            created_by=self.user,
        )
        f.full_clean()  # ne doit pas lever d'exception

    def test_facture_incoherente_leve_validation_error(self):
        from django.core.exceptions import ValidationError
        f = Facture(
            panne=self.panne,
            numero='FACT-002',
            fournisseur='Test',
            montant_ht=Decimal('100.00'),
            montant_tva=Decimal('20.00'),
            montant_ttc=Decimal('999.00'),
            date_facture=date.today(),
            created_by=self.user,
        )
        with self.assertRaises(ValidationError):
            f.full_clean()

    def test_facture_sans_lien_leve_validation_error(self):
        from django.core.exceptions import ValidationError
        f = Facture(
            numero='FACT-003',
            fournisseur='Test',
            montant_ht=Decimal('100.00'),
            montant_tva=Decimal('20.00'),
            montant_ttc=Decimal('120.00'),
            date_facture=date.today(),
            created_by=self.user,
        )
        with self.assertRaises(ValidationError):
            f.full_clean()


class ViewsPermissionsTest(TestCase):
    def setUp(self):
        self.site = Site.objects.create(nom='Site Test')
        self.admin, self.admin_pw = make_user('adm', Profile.ROLE_ADMIN, self.site)
        self.maint, self.maint_pw = make_user('mnt', Profile.ROLE_MAINTENANCE, self.site)
        self.silo, self.silo_pw = make_user('slo', Profile.ROLE_SILO, self.site)

    def test_dashboard_accessible_apres_connexion(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_connexion_redirige_si_deja_connecte(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('connexion'))
        self.assertEqual(r.status_code, 302)

    def test_site_list_interdit_silo(self):
        self.client.force_login(self.silo)
        r = self.client.get(reverse('site_list'))
        self.assertEqual(r.status_code, 403)

    def test_site_list_accessible_admin(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('site_list'))
        self.assertEqual(r.status_code, 200)

    def test_panne_create_accessible_silo(self):
        self.client.force_login(self.silo)
        r = self.client.get(reverse('panne_create'))
        self.assertEqual(r.status_code, 200)

    def test_facture_list_interdit_silo(self):
        self.client.force_login(self.silo)
        r = self.client.get(reverse('facture_list'))
        self.assertEqual(r.status_code, 403)

    def test_facture_list_accessible_maintenance(self):
        self.client.force_login(self.maint)
        r = self.client.get(reverse('facture_list'))
        self.assertEqual(r.status_code, 200)

    def test_utilisateur_list_interdit_maintenance(self):
        self.client.force_login(self.maint)
        r = self.client.get(reverse('utilisateur_list'))
        self.assertEqual(r.status_code, 403)

    def test_redirect_si_non_connecte(self):
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/connexion/', r['Location'])
