from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.timezone import localdate

from maintenance.models import OptimizedMediaMixin, Site
from maintenance.storage import private_invoice_storage


class Vehicule(OptimizedMediaMixin, models.Model):
    media_field_name = "photo"

    class Categorie(models.TextChoices):
        POIDS_LOURD = "pl", "Poids lourd"
        ENGIN_MANUTENTION = "em", "Engin de manutention"
        REMORQUE_POIDS_LOURD = "rm", "Remorque poids lourd"

    class Statut(models.TextChoices):
        DISPONIBLE = "disponible", "Disponible"
        EN_SERVICE = "en_service", "En service"
        EN_ENTRETIEN = "en_entretien", "En entretien"
        HORS_SERVICE = "hors_service", "Hors service"
        CEDE = "cede", "Cédé"

    class Carburant(models.TextChoices):
        DIESEL = "diesel", "Diesel"
        ESSENCE = "essence", "Essence"
        ELECTRIQUE = "electrique", "Électrique"
        HYBRIDE = "hybride", "Hybride"
        GAZ = "gaz", "Gaz"
        AUTRE = "autre", "Autre"

    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="vehicules",
    )
    categorie = models.CharField(max_length=2, choices=Categorie.choices)
    immatriculation = models.CharField(max_length=20, blank=True)
    marque = models.CharField(max_length=80)
    modele = models.CharField(max_length=100)
    numero_serie = models.CharField(
        max_length=50, blank=True, verbose_name="Numéro VIN")
    carburant = models.CharField(
        max_length=15,
        choices=Carburant.choices,
        default=Carburant.DIESEL,
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.DISPONIBLE,
    )
    date_mise_circulation = models.DateField(null=True, blank=True)
    kilometrage = models.PositiveIntegerField(default=0)
    date_assurance = models.DateField(
        null=True, blank=True, verbose_name="Échéance assurance")
    date_controle_technique = models.DateField(
        null=True,
        blank=True,
        verbose_name="Échéance contrôle technique",
    )
    date_mines = models.DateField(
        null=True,
        blank=True,
        verbose_name="Échéance passage aux mines",
    )
    date_vgp = models.DateField(
        null=True,
        blank=True,
        verbose_name="Échéance VGP",
    )
    organisme_vgp = models.CharField(
        max_length=100,
        blank=True,
        default="DEKRA",
        verbose_name="Organisme VGP",
    )
    rapport_vgp = models.FileField(
        upload_to="vehicules/vgp/%Y/%m/",
        storage=private_invoice_storage,
        blank=True,
        verbose_name="Rapport VGP (PDF)",
    )
    periodicite_revision_mois = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Périodicité révision (mois)",
    )
    periodicite_revision_km = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Périodicité révision (km)",
    )
    prochain_entretien_date = models.DateField(null=True, blank=True)
    prochain_entretien_km = models.PositiveIntegerField(null=True, blank=True)
    photo = models.ImageField(upload_to="vehicules/%Y/%m/", blank=True)
    notes = models.TextField(blank=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="vehicules_crees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["immatriculation"]
        constraints = [
            models.UniqueConstraint(
                fields=["immatriculation"],
                condition=~models.Q(immatriculation=""),
                name="vehicule_immatriculation_non_vide_unique",
            ),
        ]

    def __str__(self):
        identifiant = f"{self.immatriculation} - " if self.immatriculation else ""
        return f"{identifiant}{self.marque} {self.modele}"

    @staticmethod
    def _ajouter_mois(date_reference, nombre_mois):
        mois_total = date_reference.month - 1 + nombre_mois
        annee = date_reference.year + mois_total // 12
        mois = mois_total % 12 + 1
        jour = min(date_reference.day, monthrange(annee, mois)[1])
        return date(annee, mois, jour)

    def planifier_prochaine_revision(self, date_revision, kilometrage_revision):
        if self.periodicite_revision_mois:
            self.prochain_entretien_date = self._ajouter_mois(
                date_revision,
                self.periodicite_revision_mois,
            )
        if self.periodicite_revision_km:
            self.prochain_entretien_km = (
                kilometrage_revision + self.periodicite_revision_km
            )

    @property
    def prevision_revision(self):
        aujourd_hui = localdate()
        jours_restants = (
            (self.prochain_entretien_date - aujourd_hui).days
            if self.prochain_entretien_date
            else None
        )
        kilometres_restants = (
            self.prochain_entretien_km - self.kilometrage
            if self.prochain_entretien_km is not None
            else None
        )
        if jours_restants is not None and jours_restants < 0:
            statut, libelle = "en_retard", "Révision en retard"
        elif kilometres_restants is not None and kilometres_restants < 0:
            statut, libelle = "en_retard", "Révision kilométrique dépassée"
        elif (
            jours_restants is not None and jours_restants <= 30
        ) or (
            kilometres_restants is not None and kilometres_restants <= 1_000
        ):
            statut, libelle = "proche", "Révision à prévoir"
        elif jours_restants is None and kilometres_restants is None:
            statut, libelle = "non_planifiee", "Révision non planifiée"
        else:
            statut, libelle = "a_venir", "Révision planifiée"
        return {
            "statut": statut,
            "libelle": libelle,
            "jours_restants": jours_restants,
            "kilometres_restants": kilometres_restants,
        }

    @property
    def alerte_echeance(self):
        limite = localdate() + timedelta(days=30)
        dates = [
            date_echeance
            for date_echeance in (
                self.date_assurance,
                self.date_controle_technique,
                self.date_mines,
                self.date_vgp,
                self.prochain_entretien_date,
            )
            if date_echeance
        ]
        return any(date_echeance <= limite for date_echeance in dates) or (
            self.prochain_entretien_km is not None
            and self.kilometrage >= self.prochain_entretien_km
        )


class EntretienVehicule(models.Model):
    class TypeEntretien(models.TextChoices):
        REVISION = "revision", "Révision"
        REPARATION = "reparation", "Réparation"
        PNEUMATIQUES = "pneumatiques", "Pneumatiques"
        CONTROLE = "controle", "Contrôle technique"
        SINISTRE = "sinistre", "Sinistre"
        AUTRE = "autre", "Autre"

    vehicule = models.ForeignKey(
        Vehicule,
        on_delete=models.CASCADE,
        related_name="entretiens",
    )
    type_entretien = models.CharField(
        max_length=20, choices=TypeEntretien.choices)
    date_entretien = models.DateField()
    kilometrage = models.PositiveIntegerField()
    prestataire = models.CharField(max_length=150, blank=True)
    description = models.TextField()
    cout = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    facture = models.FileField(
        upload_to="vehicules/factures/%Y/%m/",
        storage=private_invoice_storage,
        blank=True,
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="entretiens_vehicules_crees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_entretien", "-cree_le"]

    def __str__(self):
        return f"{self.vehicule.immatriculation} - {self.get_type_entretien_display()}"
