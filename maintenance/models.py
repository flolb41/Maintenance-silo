from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .media_optimization import optimiser_media_televerse
from .storage import private_invoice_storage


class OptimizedMediaMixin:
    media_field_name = "fichier"

    def save(self, *args, **kwargs):
        fichier = getattr(self, self.media_field_name)
        if fichier and not fichier._committed:
            media_optimise = optimiser_media_televerse(
                fichier.file, fichier.name)
            if media_optimise is not None:
                setattr(self, self.media_field_name, media_optimise)
        return super().save(*args, **kwargs)

    @property
    def nom_telechargement(self):
        extension_stockee = Path(self.fichier.name).suffix
        return f"{Path(self.nom_original).stem}{extension_stockee}"


class Profile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrateur"
        MAINTENANCE = "maintenance", "Agent de maintenance"
        SILO = "silo", "Agent de silo"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.SILO)
    tarif_horaire = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Tarif horaire facturé par l'agent de maintenance.",
    )

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    def is_admin(self):
        return self.role == self.Role.ADMIN

    def is_maintenance(self):
        return self.role == self.Role.MAINTENANCE

    def is_silo(self):
        return self.role == self.Role.SILO


class Site(models.Model):
    nom = models.CharField(max_length=150)
    adresse = models.TextField(blank=True)
    actif = models.BooleanField(default=True)
    activite_silos = models.BooleanField(
        default=True,
        verbose_name="Activité silos",
    )
    activite_vehicules = models.BooleanField(
        default=True,
        verbose_name="Activité véhicules",
    )
    utilisateurs = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="sites_autorises",
    )

    def __str__(self):
        return self.nom

    class Meta:
        ordering = ["nom"]


class TypeGrain(models.Model):
    nom = models.CharField(max_length=100, unique=True)
    poids_specifique_moyen = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("1"))],
        help_text="Poids spécifique moyen en kg/hl.",
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Silo(models.Model):
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="silos",
    )
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["site__nom", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "nom"],
                name="unique_silo_par_site",
            ),
        ]

    def __str__(self):
        return f"{self.nom} ({self.site.nom})"


class CelluleGrain(models.Model):
    MARQUE_PRIVE = "privé"
    DIAMETRE_PRIVE_2700_T = Decimal("16.00")
    HAUTEUR_PRIVE_2700_T = Decimal("20.00")
    CAPACITE_PRIVE_2700_T = Decimal("2700.00")

    DENSITE_REFERENCE_TONNES_M3 = Decimal("0.75")
    AMPLITUDE_CONE_CAPACITE_TOLES = Decimal("1.5")

    class Forme(models.TextChoices):
        RONDE = "ronde", "Ronde"
        CARREE = "carree", "Carrée"
        RECTANGULAIRE = "rectangulaire", "Rectangulaire"

    class Etat(models.TextChoices):
        EN_SERVICE = "en_service", "En service"
        VIDE = "vide", "Vide"
        REPARATION = "reparation", "En réparation"
        NETTOYAGE = "nettoyage", "En nettoyage"

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="cellules_grain",
    )
    silo = models.ForeignKey(
        Silo,
        on_delete=models.CASCADE,
        related_name="cellules",
    )
    nom = models.CharField(max_length=100)
    type_grain = models.ForeignKey(
        TypeGrain,
        on_delete=models.PROTECT,
        related_name="cellules",
        null=True,
        blank=True,
        verbose_name="type de grain",
    )
    etat = models.CharField(
        max_length=20,
        choices=Etat.choices,
        default=Etat.EN_SERVICE,
    )
    marque = models.CharField(max_length=100, blank=True)
    forme = models.CharField(
        max_length=20,
        choices=Forme.choices,
        default=Forme.RONDE,
    )
    hauteur_m = models.DecimalField(
        "hauteur (m)",
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    diametre_m = models.DecimalField(
        "diamètre (m)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    longueur_m = models.DecimalField(
        "longueur / côté (m)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    largeur_m = models.DecimalField(
        "largeur (m)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    nombre_toles_hauteur = models.PositiveSmallIntegerField(
        "nombre de tôles en hauteur",
        default=15,
        validators=[MinValueValidator(1)],
    )
    capacite_m3 = models.DecimalField(
        "capacité totale (m³)",
        max_digits=10,
        decimal_places=2,
        default=0,
        editable=False,
    )
    capacite_tonnes = models.DecimalField(
        "capacité (t)",
        max_digits=10,
        decimal_places=2,
        editable=False,
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["site__nom", "silo__nom", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["silo", "nom"],
                name="unique_cellule_grain_par_silo",
            ),
        ]

    def __str__(self):
        return f"{self.nom} ({self.silo.nom} · {self.site.nom})"

    def clean(self):
        super().clean()
        erreurs = {}
        if self.silo_id and self.site_id and self.silo.site_id != self.site_id:
            erreurs["silo"] = "Le silo sélectionné n'appartient pas à ce site."
        if self.forme == self.Forme.RONDE and not self.diametre_m:
            erreurs["diametre_m"] = "Le diamètre est obligatoire pour une cellule ronde."
        if self.forme in {self.Forme.CARREE, self.Forme.RECTANGULAIRE} and not self.longueur_m:
            erreurs["longueur_m"] = "La longueur est obligatoire pour cette forme."
        if self.forme == self.Forme.RECTANGULAIRE and not self.largeur_m:
            erreurs["largeur_m"] = "La largeur est obligatoire pour une cellule rectangulaire."
        if self.etat == self.Etat.EN_SERVICE and not self.type_grain_id:
            erreurs["type_grain"] = (
                "Le grain est obligatoire pour une cellule en service."
            )
        if erreurs:
            raise ValidationError(erreurs)

    def calculer_surface_m2(self):
        if self.forme == self.Forme.RONDE and self.diametre_m:
            rayon = self.diametre_m / Decimal("2")
            return Decimal("3.141592653589793") * rayon * rayon
        if self.forme == self.Forme.CARREE and self.longueur_m:
            return self.longueur_m * self.longueur_m
        if self.longueur_m and self.largeur_m:
            return self.longueur_m * self.largeur_m
        return Decimal("0")

    def calculer_volume_droit_m3(self):
        return self.calculer_surface_m2() * (self.hauteur_m or Decimal("0"))

    def calculer_volume_cone_capacite_m3(self):
        if not self.nombre_toles_hauteur:
            return Decimal("0")
        hauteur_tole_m = self.hauteur_m / self.nombre_toles_hauteur
        hauteur_cone_m = hauteur_tole_m * self.AMPLITUDE_CONE_CAPACITE_TOLES
        return self.calculer_surface_m2() * hauteur_cone_m / Decimal("3")

    def calculer_capacite_m3(self):
        return (
            self.calculer_volume_droit_m3()
            + self.calculer_volume_cone_capacite_m3()
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def est_cellule_prive_2700_t(self):
        return (
            self.marque.strip().casefold() == self.MARQUE_PRIVE
            and self.forme == self.Forme.RONDE
            and self.diametre_m == self.DIAMETRE_PRIVE_2700_T
            and self.hauteur_m == self.HAUTEUR_PRIVE_2700_T
        )

    def calculer_capacite_tonnes(self):
        if self.est_cellule_prive_2700_t:
            return self.CAPACITE_PRIVE_2700_T
        densite_tonnes_m3 = (
            self.type_grain.poids_specifique_moyen / Decimal("100")
            if self.type_grain_id
            else self.DENSITE_REFERENCE_TONNES_M3
        )
        return (
            self.calculer_capacite_m3() * densite_tonnes_m3
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if self.silo_id:
            self.site_id = self.silo.site_id
        elif self.site_id:
            self.silo, _ = Silo.objects.get_or_create(
                site_id=self.site_id,
                nom="Silo principal",
            )
        if self.etat != self.Etat.EN_SERVICE:
            self.type_grain = None
        self.capacite_m3 = self.calculer_capacite_m3()
        self.capacite_tonnes = self.calculer_capacite_tonnes()
        return super().save(*args, **kwargs)

    @property
    def peut_recevoir_stock(self):
        return (
            self.actif
            and self.etat == self.Etat.EN_SERVICE
            and self.type_grain_id is not None
        )

    @property
    def dernier_releve(self):
        if hasattr(self, "derniers_releves_prefetches"):
            return (
                self.derniers_releves_prefetches[0]
                if self.derniers_releves_prefetches
                else None
            )
        return self.releves.first()


class ReleveCellule(models.Model):
    class FormeSurface(models.TextChoices):
        SORTANT_PETIT = "sortant_petit", "Cône sortant petit"
        SORTANT_MOYEN = "sortant_moyen", "Cône sortant moyen"
        SORTANT_GRAND = "sortant_grand", "Cône sortant grand"
        AUCUNE = "aucune", "Pas de cône"
        RENTRANT_PETIT = "rentrant_petit", "Cône rentrant petit"
        RENTRANT_MOYEN = "rentrant_moyen", "Cône rentrant moyen"
        RENTRANT_GRAND = "rentrant_grand", "Cône rentrant grand"

    AMPLITUDES_CONE_TOLES = {
        FormeSurface.SORTANT_PETIT: Decimal("0.5"),
        FormeSurface.SORTANT_MOYEN: Decimal("1"),
        FormeSurface.SORTANT_GRAND: Decimal("1.5"),
        FormeSurface.AUCUNE: Decimal("0"),
        FormeSurface.RENTRANT_PETIT: Decimal("-0.5"),
        FormeSurface.RENTRANT_MOYEN: Decimal("-1"),
        FormeSurface.RENTRANT_GRAND: Decimal("-1.5"),
    }

    cellule = models.ForeignKey(
        CelluleGrain,
        on_delete=models.CASCADE,
        related_name="releves",
    )
    type_grain = models.ForeignKey(
        TypeGrain,
        on_delete=models.PROTECT,
        related_name="releves",
    )
    masse_estimee_tonnes = models.DecimalField(
        "masse estimée (t)",
        max_digits=10,
        decimal_places=2,
        default=0,
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    tonnage_manuel = models.DecimalField(
        "tonnage manuel (t)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Laissez vide pour calculer le tonnage à partir des tôles.",
    )
    nombre_toles_vides = models.DecimalField(
        "nombre de tôles vides",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Le comptage peut être saisi par quart de tôle.",
    )
    forme_surface = models.CharField(
        "forme de la surface du grain",
        max_length=20,
        choices=FormeSurface.choices,
        default=FormeSurface.AUCUNE,
    )
    poids_specifique_kg_hl = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        editable=False,
    )
    releve_le = models.DateTimeField(default=timezone.now)
    releve_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="releves_cellules",
    )
    commentaire = models.TextField(blank=True)

    class Meta:
        ordering = ["-releve_le", "-pk"]

    def clean(self):
        super().clean()
        if (
            self.cellule_id
            and self.nombre_toles_vides is not None
            and self.nombre_toles_vides > self.cellule.nombre_toles_hauteur
        ):
            raise ValidationError({
                "nombre_toles_vides": (
                    "Le nombre de tôles vides ne peut pas dépasser les "
                    f"{self.cellule.nombre_toles_hauteur} tôles de la cellule."
                ),
            })

    def save(self, *args, **kwargs):
        if not self.type_grain_id and self.cellule_id:
            self.type_grain_id = self.cellule.type_grain_id
        if not self.type_grain_id:
            raise ValidationError(
                "Configurez le type de grain de la cellule avant de saisir son stock."
            )
        if not self.pk or not self.poids_specifique_kg_hl:
            self.poids_specifique_kg_hl = self.type_grain.poids_specifique_moyen
        densite_tonnes_m3 = self.poids_specifique_kg_hl / Decimal("100")
        if self.tonnage_manuel is not None:
            self.masse_estimee_tonnes = self.tonnage_manuel
        else:
            self.masse_estimee_tonnes = (
                self.calculer_volume_geometrique_m3() * densite_tonnes_m3
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return super().save(*args, **kwargs)

    def calculer_volume_estime_m3(self):
        if self.tonnage_manuel is not None:
            poids_specifique = (
                self.poids_specifique_kg_hl
                or self.type_grain.poids_specifique_moyen
            )
            densite_tonnes_m3 = poids_specifique / Decimal("100")
            return (self.tonnage_manuel / densite_tonnes_m3).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return self.calculer_volume_geometrique_m3()

    def calculer_volume_geometrique_m3(self):
        cellule = self.cellule
        if not cellule.hauteur_m or not cellule.nombre_toles_hauteur:
            return Decimal("0")
        surface_m2 = cellule.calculer_surface_m2()
        hauteur_tole_m = cellule.hauteur_m / cellule.nombre_toles_hauteur
        hauteur_droite_m = max(
            Decimal("0"),
            cellule.hauteur_m - self.nombre_toles_vides * hauteur_tole_m,
        )
        amplitude = self.AMPLITUDES_CONE_TOLES[self.forme_surface]
        volume_cone_m3 = surface_m2 * hauteur_tole_m * amplitude / Decimal("3")
        return max(
            Decimal("0"),
            surface_m2 * hauteur_droite_m + volume_cone_m3,
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def volume_estime_m3(self):
        return self.calculer_volume_estime_m3()

    @property
    def taux_remplissage(self):
        if self.cellule.est_cellule_prive_2700_t:
            return (
                self.masse_estimee_tonnes
                / self.cellule.CAPACITE_PRIVE_2700_T
                * Decimal("100")
            )
        volume = self.volume_estime_m3
        if volume is None or not self.cellule.capacite_m3:
            return None
        return (volume / self.cellule.capacite_m3) * Decimal("100")


class StockageAPlat(models.Model):
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="stockages_a_plat",
    )
    nom = models.CharField(max_length=100)
    type_grain = models.ForeignKey(
        TypeGrain,
        on_delete=models.PROTECT,
        related_name="stockages_a_plat",
        verbose_name="type de grain",
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["site__nom", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "nom"],
                name="unique_stockage_a_plat_par_site",
            ),
        ]

    def __str__(self):
        return f"{self.nom} ({self.site.nom})"

    @property
    def dernier_releve(self):
        if hasattr(self, "derniers_releves_prefetches"):
            return (
                self.derniers_releves_prefetches[0]
                if self.derniers_releves_prefetches
                else None
            )
        return self.releves.first()

    @property
    def derniers_releves_par_grain(self):
        releves = getattr(self, "releves_prefetches", None)
        if releves is None:
            releves = self.releves.select_related("type_grain").all()
        derniers = {}
        for releve in releves:
            derniers.setdefault(releve.type_grain_id, releve)
        return list(derniers.values())


class ReleveStockageAPlat(models.Model):
    stockage = models.ForeignKey(
        StockageAPlat,
        on_delete=models.CASCADE,
        related_name="releves",
    )
    type_grain = models.ForeignKey(
        TypeGrain,
        on_delete=models.PROTECT,
        related_name="releves_stockages_a_plat",
        verbose_name="type de grain",
    )
    tonnage = models.DecimalField(
        "tonnage (t)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    releve_le = models.DateTimeField(default=timezone.now)
    releve_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="releves_stockages_a_plat",
    )
    commentaire = models.TextField(blank=True)

    class Meta:
        ordering = ["-releve_le", "-pk"]

    def __str__(self):
        return f"{self.stockage} : {self.tonnage} t"

    def save(self, *args, **kwargs):
        if self.stockage_id and not self.type_grain_id:
            self.type_grain_id = self.stockage.type_grain_id
        return super().save(*args, **kwargs)


class SitePhoto(OptimizedMediaMixin, models.Model):
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    fichier = models.ImageField(upload_to="sites/%Y/%m/")
    nom_original = models.CharField(max_length=255)
    ajoutee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="photos_sites_ajoutees",
    )
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]

    def __str__(self):
        return f"Photo de {self.site.nom}"


class Equipement(models.Model):
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="equipements")
    equipement_parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sous_equipements",
        verbose_name="Équipement parent",
    )
    nom = models.CharField(max_length=150)
    reference = models.CharField(max_length=100, blank=True)
    actif = models.BooleanField(default=True)

    def __str__(self):
        if self.equipement_parent_id:
            return f"{self.equipement_parent.nom} > {self.nom} ({self.site.nom})"
        return f"{self.nom} ({self.site.nom})"

    class Meta:
        ordering = ["nom"]


class PieceDetachee(models.Model):
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="pieces_detachees")
    reference = models.CharField(max_length=100)
    nom = models.CharField(max_length=150)
    stock = models.PositiveIntegerField(default=0)
    seuil_alerte = models.PositiveIntegerField(default=1)
    emplacement = models.CharField(max_length=100, blank=True)
    fournisseur = models.CharField(max_length=150, blank=True)
    actif = models.BooleanField(default=True)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "reference"], name="unique_piece_reference_site"),
        ]

    @property
    def sous_seuil(self):
        return self.stock <= self.seuil_alerte

    def __str__(self):
        return f"{self.reference} - {self.nom} ({self.site.nom})"


class MouvementPiece(models.Model):
    ENTREE = "entree"
    SORTIE = "sortie"
    TYPES = [(ENTREE, "Entrée"), (SORTIE, "Sortie")]
    piece = models.ForeignKey(
        PieceDetachee, on_delete=models.CASCADE, related_name="mouvements")
    type_mouvement = models.CharField(max_length=10, choices=TYPES)
    quantite = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    commentaire = models.CharField(max_length=255, blank=True)
    effectue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]


# ---------------------------------------------------------------------------
# Pannes
# ---------------------------------------------------------------------------

class Panne(models.Model):
    STATUT_NOUVELLE = "nouvelle"
    STATUT_AFFECTEE = "affectee"
    STATUT_EN_COURS = "en_cours"
    STATUT_ATTENTE_PIECES = "attente_piece"
    STATUT_IMPREVUS = "imprevus"
    STATUT_TERMINEE = "resolue"
    STATUT_ARCHIVEE = "cloturee"
    STATUT_ANNULEE = "annulee"
    PRIORITE_CRITIQUE = "critique"
    STATUTS = [
        (STATUT_NOUVELLE, "Nouvelle"),
        (STATUT_AFFECTEE, "Affectée"),
        (STATUT_EN_COURS, "En cours"),
        (STATUT_ATTENTE_PIECES, "En attente de pièces"),
        (STATUT_IMPREVUS, "Imprévus"),
        (STATUT_TERMINEE, "Terminée"),
        (STATUT_ARCHIVEE, "Archivée"),
        (STATUT_ANNULEE, "Annulée"),
    ]

    class Statut(models.TextChoices):
        NOUVELLE = "nouvelle", "Nouvelle"
        AFFECTEE = "affectee", "Affectée"
        EN_COURS = "en_cours", "En cours"
        ATTENTE_PIECE = "attente_piece", "En attente de pièce"
        IMPREVUS = "imprevus", "Imprévus"
        RESOLUE = "resolue", "Terminée"
        CLOTUREE = "cloturee", "Archivée"

    class Priorite(models.TextChoices):
        BASSE = "basse", "Basse"
        NORMALE = "normale", "Normale"
        HAUTE = "haute", "Haute"
        CRITIQUE = "critique", "Critique"

    PRIORITES = [
        (Priorite.BASSE, "Basse"),
        (Priorite.NORMALE, "Normale"),
        (Priorite.HAUTE, "Haute"),
        (Priorite.CRITIQUE, "Critique"),
    ]

    # Transitions autorisées : statut_actuel → [statuts_cibles]
    TRANSITIONS_AUTORISEES = {
        Statut.NOUVELLE: [Statut.AFFECTEE],
        Statut.AFFECTEE: [
            Statut.EN_COURS,
            Statut.ATTENTE_PIECE,
            Statut.IMPREVUS,
            Statut.RESOLUE,
            Statut.NOUVELLE,
        ],
        Statut.EN_COURS: [Statut.ATTENTE_PIECE, Statut.IMPREVUS, Statut.RESOLUE],
        Statut.ATTENTE_PIECE: [Statut.EN_COURS, Statut.IMPREVUS, Statut.RESOLUE],
        Statut.IMPREVUS: [Statut.EN_COURS, Statut.ATTENTE_PIECE, Statut.RESOLUE],
        Statut.RESOLUE: [Statut.CLOTUREE, Statut.EN_COURS],
        Statut.CLOTUREE: [],
    }

    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="pannes")
    equipement = models.ForeignKey(
        Equipement, on_delete=models.PROTECT, null=True, blank=True, related_name="pannes"
    )
    signale_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pannes_declarees",
        db_column="declarant_id",
    )
    affecte_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pannes_assignees",
        db_column="agent_assigne_id",
    )
    titre = models.CharField(max_length=200)
    description = models.TextField()
    priorite = models.CharField(
        max_length=20, choices=Priorite.choices, default=Priorite.NORMALE
    )
    statut = models.CharField(
        max_length=30, choices=Statut.choices, default=Statut.NOUVELLE
    )
    commentaire_resolution = models.TextField(blank=True)
    date_signalement = models.DateTimeField(
        auto_now_add=True, db_column="creee_le")
    date_resolution = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_column="modifiee_le")

    def __str__(self):
        return f"[{self.get_statut_display()}] {self.titre}"

    @property
    def declarant(self):
        return self.signale_par

    @declarant.setter
    def declarant(self, value):
        self.signale_par = value

    @property
    def agent_assigne(self):
        return self.affecte_a

    @agent_assigne.setter
    def agent_assigne(self, value):
        self.affecte_a = value

    @property
    def creee_le(self):
        return self.date_signalement

    @property
    def modifiee_le(self):
        return self.updated_at

    @property
    def total_temps_minutes(self):
        return sum(
            item.duree_minutes for item in self.temps_interventions.filter(validee=True)
        )

    @property
    def cout_total_intervention(self):
        return sum(
            (item.montant for item in self.temps_interventions.filter(validee=True)),
            start=Decimal("0.00"),
        )

    @property
    def cout_total_global(self):
        total_factures = self.factures.aggregate(
            total=models.Sum('montant_ht')
        )['total'] or Decimal('0.00')
        return self.cout_total_intervention + total_factures

    def save(self, *args, **kwargs):
        if self.created_at is None:
            self.created_at = timezone.now()
        if self.statut in {self.STATUT_TERMINEE, self.STATUT_ARCHIVEE}:
            self.date_resolution = self.date_resolution or timezone.now()
        super().save(*args, **kwargs)

    def changer_statut(self, nouveau_statut, user=None, commentaire=""):
        if nouveau_statut not in {choice[0] for choice in self.STATUTS}:
            raise ValueError("Statut non autorisé.")
        if self.statut == nouveau_statut:
            return self
        if nouveau_statut not in self.TRANSITIONS_AUTORISEES.get(self.statut, []):
            raise ValueError("Transition de statut non autorisée.")
        ancien = self.statut
        self.statut = nouveau_statut
        if user is not None:
            HistoriquePanne.objects.create(
                panne=self,
                ancien_statut=ancien,
                nouveau_statut=nouveau_statut,
                modifie_par=user,
                commentaire=commentaire or "",
            )
        self.save(update_fields=["statut", "updated_at", "date_resolution"])
        return self

    class Meta:
        ordering = ["-date_signalement"]


class PanneMedia(OptimizedMediaMixin, models.Model):
    panne = models.ForeignKey(
        Panne, on_delete=models.CASCADE, related_name="medias")
    fichier = models.FileField(upload_to="pannes/%Y/%m/")
    nom_original = models.CharField(max_length=255)
    ajoute_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pannes_medias"
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Média panne #{self.panne_id} – {self.nom_original}"


# ---------------------------------------------------------------------------
# Maintenances préventives
# ---------------------------------------------------------------------------

class MaintenancePreventive(models.Model):
    class Periodicite(models.TextChoices):
        PONCTUELLE = "ponctuelle", "Ponctuelle"
        MENSUELLE = "mensuelle", "Mensuelle"
        TRIMESTRIELLE = "trimestrielle", "Trimestrielle"
        ANNUELLE = "annuelle", "Annuelle"

    STATUT_BROUILLON = "brouillon"
    STATUT_ENVOYEE = "envoyee"
    STATUT_RECUE = "recue"
    STATUT_EN_COURS = "en_cours"
    STATUT_A_VALIDER = "a_valider"
    STATUT_VALIDEE = "validee"
    STATUT_REJETEE = "rejetee"
    STATUT_EN_RETARD = "en_retard"
    STATUT_EFFECTUEE = "effectuee"
    STATUT_PRISE_EN_COMPTE = "prise_en_compte"
    STATUT_EN_ATTENTE = "en_attente"
    STATUT_ARCHIVEE = "archivee"
    STATUT_ANNULEE = "annulee"
    STATUT_PLANIFIEE = "planifiee"
    STATUTS = [
        (STATUT_BROUILLON, "Brouillon"),
        (STATUT_ENVOYEE, "Envoyée"),
        (STATUT_RECUE, "Reçue"),
        (STATUT_EN_COURS, "En cours"),
        (STATUT_A_VALIDER, "À valider"),
        (STATUT_VALIDEE, "Validée"),
        (STATUT_REJETEE, "Rejetée"),
        (STATUT_EN_RETARD, "En retard"),
        (STATUT_EFFECTUEE, "Terminée"),
        (STATUT_PRISE_EN_COMPTE, "Prise en compte"),
        (STATUT_EN_ATTENTE, "En attente"),
        (STATUT_ARCHIVEE, "Archivée"),
        (STATUT_ANNULEE, "Annulée"),
        (STATUT_PLANIFIEE, "Planifiée"),
    ]

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        ENVOYEE = "envoyee", "Envoyée"
        RECUE = "recue", "Reçue"
        EN_COURS = "en_cours", "En cours"
        A_VALIDER = "a_valider", "À valider"
        VALIDEE = "validee", "Validée"
        REJETEE = "rejetee", "Rejetée"
        EN_RETARD = "en_retard", "En retard"
        EFFECTUEE = "effectuee", "Terminée"
        PRISE_EN_COMPTE = "prise_en_compte", "Prise en compte"
        EN_ATTENTE = "en_attente", "En attente"
        ARCHIVEE = "archivee", "Archivée"
        ANNULEE = "annulee", "Annulée"
        PLANIFIEE = "planifiee", "Planifiée"

    # Transitions autorisées : statut_actuel → [statuts_cibles]
    TRANSITIONS_AUTORISEES = {
        Statut.BROUILLON: [Statut.ENVOYEE, Statut.EFFECTUEE],
        Statut.ENVOYEE: [Statut.RECUE, Statut.EN_RETARD, Statut.EFFECTUEE],
        Statut.RECUE: [Statut.EN_COURS, Statut.EN_RETARD, Statut.EFFECTUEE],
        Statut.EN_COURS: [Statut.A_VALIDER, Statut.EFFECTUEE],
        Statut.A_VALIDER: [Statut.VALIDEE, Statut.REJETEE, Statut.EFFECTUEE],
        Statut.VALIDEE: [Statut.EFFECTUEE, Statut.ARCHIVEE],
        Statut.REJETEE: [Statut.ENVOYEE, Statut.EFFECTUEE],
        Statut.EN_RETARD: [Statut.EFFECTUEE],
        Statut.PLANIFIEE: [Statut.PRISE_EN_COMPTE, Statut.ANNULEE],
        Statut.PRISE_EN_COMPTE: [Statut.EN_COURS, Statut.EN_ATTENTE, Statut.EFFECTUEE],
        Statut.EN_ATTENTE: [Statut.EN_COURS, Statut.EFFECTUEE],
        Statut.EFFECTUEE: [Statut.ARCHIVEE],
        Statut.ARCHIVEE: [],
        Statut.ANNULEE: [],
    }

    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="maintenances_preventives"
    )
    equipement = models.ForeignKey(
        Equipement,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="maintenances_preventives",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenances_creees",
        db_column="createur_id",
    )
    affecte_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenances_recues",
        db_column="destinataire_id",
    )
    titre = models.CharField(max_length=200)
    description = models.TextField(db_column="instructions")
    date_echeance = models.DateTimeField(db_column="echeance")
    periodicite = models.CharField(
        max_length=20,
        choices=Periodicite.choices,
        default=Periodicite.PONCTUELLE,
    )
    recurrence_active = models.BooleanField(default=False)
    recurrence_jusquau = models.DateField(null=True, blank=True)
    serie_parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="occurrences",
    )
    statut = models.CharField(
        max_length=30, choices=Statut.choices, default=Statut.BROUILLON
    )
    retour_intervention = models.TextField(blank=True, db_column="retour")
    commentaire_validation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_column="creee_le")
    updated_at = models.DateTimeField(auto_now=True, db_column="modifiee_le")

    @property
    def createur(self):
        return self.created_by

    @createur.setter
    def createur(self, value):
        self.created_by = value

    @property
    def destinataire(self):
        return self.affecte_a

    @destinataire.setter
    def destinataire(self, value):
        self.affecte_a = value

    @property
    def instructions(self):
        return self.description

    @instructions.setter
    def instructions(self, value):
        self.description = value

    @property
    def echeance(self):
        return self.date_echeance

    @echeance.setter
    def echeance(self, value):
        self.date_echeance = value

    @property
    def retour(self):
        return self.retour_intervention

    @retour.setter
    def retour(self, value):
        self.retour_intervention = value

    @property
    def creee_le(self):
        return self.created_at

    @property
    def modifiee_le(self):
        return self.updated_at

    def changer_statut(self, nouveau_statut, user=None, commentaire=""):
        if nouveau_statut not in {choice[0] for choice in self.STATUTS}:
            raise ValueError("Statut non autorisé.")
        if self.statut == nouveau_statut:
            return self
        if nouveau_statut not in self.TRANSITIONS_AUTORISEES.get(self.statut, []):
            raise ValueError("Transition de statut non autorisée.")
        ancien = self.statut
        self.statut = nouveau_statut
        if user is not None:
            HistoriquePreventive.objects.create(
                preventive=self,
                ancien_statut=ancien,
                nouveau_statut=nouveau_statut,
                modifie_par=user,
                commentaire=commentaire or "",
            )
        self.save(update_fields=["statut", "updated_at"])
        return self

    def recevoir(self, user=None):
        self.changer_statut(self.Statut.RECUE, user=user, commentaire="")
        return self

    def demarrer(self, user=None):
        self.changer_statut(self.Statut.EN_COURS, user=user, commentaire="")
        return self

    def terminer(self, user=None, retour=""):
        self.retour_intervention = retour
        self.changer_statut(self.Statut.A_VALIDER,
                            user=user, commentaire=retour)
        return self

    def valider(self, user=None, commentaire=""):
        self.changer_statut(self.Statut.VALIDEE, user=user,
                            commentaire=commentaire)
        return self

    def prochaine_echeance_apres(self, echeance):
        mois_par_periode = {
            self.Periodicite.MENSUELLE: 1,
            self.Periodicite.TRIMESTRIELLE: 3,
            self.Periodicite.ANNUELLE: 12,
        }
        mois_a_ajouter = mois_par_periode.get(self.periodicite)
        if mois_a_ajouter is None:
            return None

        index_mois = echeance.month - 1 + mois_a_ajouter
        annee = echeance.year + index_mois // 12
        mois = index_mois % 12 + 1
        jour = min(self.date_echeance.day, monthrange(annee, mois)[1])
        return echeance.replace(year=annee, month=mois, day=jour)

    def __str__(self):
        return f"[{self.get_statut_display()}] {self.titre}"

    def est_en_retard(self):
        return self.date_echeance < timezone.now() and self.statut not in (
            self.Statut.VALIDEE,
            self.Statut.CLOTUREE if hasattr(self.Statut, "CLOTUREE") else "",
        )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["serie_parent", "date_echeance"],
                name="unique_echeance_serie_preventive",
            ),
        ]


class PreventiveMedia(OptimizedMediaMixin, models.Model):
    preventive = models.ForeignKey(
        MaintenancePreventive, on_delete=models.CASCADE, related_name="medias"
    )
    fichier = models.FileField(upload_to="preventives/%Y/%m/")
    nom_original = models.CharField(max_length=255)
    ajoute_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="preventives_medias",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Média préventive #{self.preventive_id} – {self.nom_original}"


# ---------------------------------------------------------------------------
# Factures
# ---------------------------------------------------------------------------

class Facture(models.Model):
    TYPE_AUTRE = "autre"
    TYPE_MAINTENANCE = "maintenance"
    TYPE_REVISION = "revision"
    TYPES = [
        (TYPE_AUTRE, "Autre"),
        (TYPE_MAINTENANCE, "Maintenance"),
        (TYPE_REVISION, "Révision"),
    ]
    STATUT_BROUILLON = "brouillon"
    STATUT_VALIDE = "valide"
    STATUT_REJETE = "rejete"
    STATUTS = [
        (STATUT_BROUILLON, "Brouillon"),
        (STATUT_VALIDE, "Validée"),
        (STATUT_REJETE, "Rejetée"),
    ]
    DETECTION_OK = "ok"
    DETECTION_INCOMPLETE = "incomplete"

    panne = models.ForeignKey(
        Panne,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="factures",
    )
    preventive = models.ForeignKey(
        MaintenancePreventive,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="factures",
    )
    numero = models.CharField(max_length=100)
    fournisseur = models.CharField(max_length=150)
    type_facture = models.CharField(
        max_length=20, choices=TYPES, default=TYPE_AUTRE)
    statut = models.CharField(
        max_length=20, choices=STATUTS, default=STATUT_BROUILLON)
    statut_detection = models.CharField(
        max_length=20,
        choices=[
            (DETECTION_OK, "Complète"),
            (DETECTION_INCOMPLETE, "Incomplète"),
        ],
        default=DETECTION_INCOMPLETE,
    )
    score_detection = models.PositiveSmallIntegerField(default=0)
    details_detection = models.JSONField(default=dict, blank=True)
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    montant_tva = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    montant_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    date_facture = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    fichier = models.FileField(
        upload_to="factures/%Y/%m/",
        storage=private_invoice_storage,
        blank=True,
    )
    nom_fichier_original = models.CharField(max_length=255, blank=True)
    validee = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="factures_creees",
    )
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.validee = self.statut == self.STATUT_VALIDE
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Facture {self.numero} – {self.fournisseur}"

    class Meta:
        ordering = ["-creee_le"]


class PanneTempsIntervention(models.Model):
    panne = models.ForeignKey(
        Panne,
        on_delete=models.CASCADE,
        related_name="temps_interventions",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="temps_interventions_realises",
    )
    date_intervention = models.DateField(default=timezone.localdate)
    duree_minutes = models.PositiveIntegerField(default=0)
    commentaire = models.TextField(blank=True)
    montant = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    validee = models.BooleanField(
        default=False, help_text="Validé par l'administration.")
    creee_le = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.duree_minutes and self.agent_id:
            try:
                profile = self.agent.profile
            except Profile.DoesNotExist:
                profile = None
            if profile is not None and profile.tarif_horaire:
                heures = Decimal(self.duree_minutes) / Decimal(60)
                self.montant = heures * profile.tarif_horaire
        else:
            self.montant = Decimal(str(self.montant or 0))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Intervention {self.agent.username} - {self.duree_minutes} min"

    class Meta:
        ordering = ["-date_intervention", "-creee_le"]


class HistoriquePanne(models.Model):
    panne = models.ForeignKey(
        Panne, on_delete=models.CASCADE, related_name="historiques")
    ancien_statut = models.CharField(max_length=30, blank=True, default="")
    nouveau_statut = models.CharField(max_length=30, blank=True, default="")
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historique_pannes",
    )
    commentaire = models.TextField(blank=True)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]


class HistoriquePreventive(models.Model):
    preventive = models.ForeignKey(
        MaintenancePreventive,
        on_delete=models.CASCADE,
        related_name="historiques",
    )
    ancien_statut = models.CharField(max_length=30, blank=True, default="")
    nouveau_statut = models.CharField(max_length=30, blank=True, default="")
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historique_preventives",
    )
    commentaire = models.TextField(blank=True)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(models.Model):
    class TypeNotif(models.TextChoices):
        PANNE_CREEE = "panne_creee", "Panne créée"
        PANNE_AFFECTEE = "panne_affectee", "Panne affectée"
        PANNE_STATUT = "panne_statut", "Changement statut panne"
        PREVENTIVE_RECUE = "preventive_recue", "Tâche préventive reçue"
        PREVENTIVE_DEMARREE = "preventive_demarree", "Tâche démarrée"
        PREVENTIVE_TERMINEE = "preventive_terminee", "Tâche terminée"
        PREVENTIVE_VALIDEE = "preventive_validee", "Tâche validée"
        PREVENTIVE_REJETEE = "preventive_rejetee", "Tâche rejetée"
        PREVENTIVE_RETARD = "preventive_retard", "Tâche en retard"
        FACTURE_AJOUTEE = "facture_ajoutee", "Facture ajoutée"
        MEDIA_AJOUTE = "media_ajoute", "Média ajouté"

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type_notif = models.CharField(
        max_length=30, choices=TypeNotif.choices, default=TypeNotif.PANNE_CREEE
    )
    titre = models.CharField(max_length=200)
    message = models.TextField()
    lue = models.BooleanField(default=False)
    lien = models.CharField(max_length=300, blank=True)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]

    def __str__(self):
        return f"Notification [{self.type_notif}] pour {self.utilisateur.username}"
