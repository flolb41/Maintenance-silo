from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal


class Site(models.Model):
    nom = models.CharField(max_length=200)
    adresse = models.TextField(blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nom']
        verbose_name = 'Site'
        verbose_name_plural = 'Sites'

    def __str__(self):
        return self.nom


class Profile(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_MAINTENANCE = 'maintenance'
    ROLE_SILO = 'silo'
    ROLES = [
        (ROLE_ADMIN, 'Administrateur'),
        (ROLE_MAINTENANCE, 'Équipe maintenance'),
        (ROLE_SILO, 'Agent silo'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLES, default=ROLE_SILO)
    sites = models.ManyToManyField(Site, blank=True, related_name='profiles')
    telephone = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = 'Profil'
        verbose_name_plural = 'Profils'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_role_display()})"

    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    def is_maintenance(self):
        return self.role == self.ROLE_MAINTENANCE

    def is_silo(self):
        return self.role == self.ROLE_SILO


class Equipement(models.Model):
    CATEGORIE_CHOICES = [
        ('convoyeur', 'Convoyeur'),
        ('elevateur', 'Élévateur'),
        ('ventilateur', 'Ventilateur'),
        ('sonde', 'Sonde / Capteur'),
        ('electrique', 'Équipement électrique'),
        ('mecanique', 'Équipement mécanique'),
        ('autre', 'Autre'),
    ]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='equipements')
    nom = models.CharField(max_length=200)
    reference = models.CharField(max_length=100, blank=True)
    categorie = models.CharField(max_length=50, choices=CATEGORIE_CHOICES, default='autre')
    description = models.TextField(blank=True)
    date_installation = models.DateField(null=True, blank=True)
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['site', 'nom']
        verbose_name = 'Équipement'
        verbose_name_plural = 'Équipements'

    def __str__(self):
        return f"{self.nom} — {self.site.nom}"


class Panne(models.Model):
    PRIORITE_BASSE = 'basse'
    PRIORITE_NORMALE = 'normale'
    PRIORITE_HAUTE = 'haute'
    PRIORITE_CRITIQUE = 'critique'
    PRIORITES = [
        (PRIORITE_BASSE, 'Basse'),
        (PRIORITE_NORMALE, 'Normale'),
        (PRIORITE_HAUTE, 'Haute'),
        (PRIORITE_CRITIQUE, 'Critique'),
    ]

    STATUT_NOUVELLE = 'nouvelle'
    STATUT_AFFECTEE = 'affectee'
    STATUT_EN_COURS = 'en_cours'
    STATUT_EN_ATTENTE = 'en_attente_pieces'
    STATUT_RESOLUE = 'resolue'
    STATUT_FERMEE = 'fermee'
    STATUT_ANNULEE = 'annulee'
    STATUTS = [
        (STATUT_NOUVELLE, 'Nouvelle'),
        (STATUT_AFFECTEE, 'Affectée'),
        (STATUT_EN_COURS, 'En cours'),
        (STATUT_EN_ATTENTE, 'En attente de pièces'),
        (STATUT_RESOLUE, 'Résolue'),
        (STATUT_FERMEE, 'Fermée'),
        (STATUT_ANNULEE, 'Annulée'),
    ]

    TRANSITIONS_AUTORISEES = {
        STATUT_NOUVELLE: [STATUT_AFFECTEE, STATUT_ANNULEE],
        STATUT_AFFECTEE: [STATUT_EN_COURS, STATUT_ANNULEE],
        STATUT_EN_COURS: [STATUT_EN_ATTENTE, STATUT_RESOLUE],
        STATUT_EN_ATTENTE: [STATUT_EN_COURS, STATUT_ANNULEE],
        STATUT_RESOLUE: [STATUT_FERMEE],
        STATUT_FERMEE: [],
        STATUT_ANNULEE: [],
    }

    equipement = models.ForeignKey(Equipement, on_delete=models.CASCADE, related_name='pannes')
    titre = models.CharField(max_length=300)
    description = models.TextField()
    priorite = models.CharField(max_length=20, choices=PRIORITES, default=PRIORITE_NORMALE)
    statut = models.CharField(max_length=30, choices=STATUTS, default=STATUT_NOUVELLE)
    signale_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='pannes_signalee')
    affecte_a = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pannes_affectees')
    date_signalement = models.DateTimeField(default=timezone.now)
    date_resolution = models.DateTimeField(null=True, blank=True)
    solution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_signalement']
        verbose_name = 'Panne'
        verbose_name_plural = 'Pannes'

    def __str__(self):
        return f"[{self.get_priorite_display()}] {self.titre} — {self.equipement}"

    def peut_transitionner_vers(self, nouveau_statut):
        return nouveau_statut in self.TRANSITIONS_AUTORISEES.get(self.statut, [])

    def changer_statut(self, nouveau_statut, utilisateur, commentaire=''):
        if not self.peut_transitionner_vers(nouveau_statut):
            raise ValueError(
                f"Transition interdite : {self.statut} → {nouveau_statut}"
            )
        ancien_statut = self.statut
        self.statut = nouveau_statut
        if nouveau_statut == self.STATUT_RESOLUE:
            self.date_resolution = timezone.now()
        self.save()
        HistoriquePanne.objects.create(
            panne=self,
            ancien_statut=ancien_statut,
            nouveau_statut=nouveau_statut,
            modifie_par=utilisateur,
            commentaire=commentaire,
        )
        return self


class HistoriquePanne(models.Model):
    panne = models.ForeignKey(Panne, on_delete=models.CASCADE, related_name='historique')
    ancien_statut = models.CharField(max_length=30)
    nouveau_statut = models.CharField(max_length=30)
    modifie_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    commentaire = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        verbose_name = 'Historique panne'
        verbose_name_plural = 'Historique pannes'

    def __str__(self):
        return f"{self.panne.titre} : {self.ancien_statut} → {self.nouveau_statut}"


class PanneMedia(models.Model):
    panne = models.ForeignKey(Panne, on_delete=models.CASCADE, related_name='medias')
    fichier = models.FileField(upload_to='pannes/')
    legende = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Média panne'
        verbose_name_plural = 'Médias pannes'

    def __str__(self):
        return f"Média de {self.panne.titre}"


class MaintenancePreventive(models.Model):
    STATUT_PLANIFIEE = 'planifiee'
    STATUT_EN_COURS = 'en_cours'
    STATUT_EN_ATTENTE = 'en_attente_pieces'
    STATUT_EFFECTUEE = 'effectuee'
    STATUT_VALIDEE = 'validee'
    STATUT_ANNULEE = 'annulee'
    STATUT_EN_RETARD = 'en_retard'
    STATUT_REPORTEE = 'reportee'
    STATUT_PARTIELLE = 'partielle'
    STATUT_ARCHIVEE = 'archivee'
    STATUTS = [
        (STATUT_PLANIFIEE, 'Planifiée'),
        (STATUT_EN_COURS, 'En cours'),
        (STATUT_EN_ATTENTE, 'En attente de pièces'),
        (STATUT_EFFECTUEE, 'Effectuée'),
        (STATUT_VALIDEE, 'Validée'),
        (STATUT_ANNULEE, 'Annulée'),
        (STATUT_EN_RETARD, 'En retard'),
        (STATUT_REPORTEE, 'Reportée'),
        (STATUT_PARTIELLE, 'Partielle'),
        (STATUT_ARCHIVEE, 'Archivée'),
    ]

    TRANSITIONS_AUTORISEES = {
        STATUT_PLANIFIEE: [STATUT_EN_COURS, STATUT_ANNULEE, STATUT_EN_RETARD, STATUT_REPORTEE],
        STATUT_EN_COURS: [STATUT_EN_ATTENTE, STATUT_EFFECTUEE, STATUT_PARTIELLE],
        STATUT_EN_ATTENTE: [STATUT_EN_COURS, STATUT_ANNULEE],
        STATUT_EFFECTUEE: [STATUT_VALIDEE],
        STATUT_VALIDEE: [STATUT_ARCHIVEE],
        STATUT_ANNULEE: [],
        STATUT_EN_RETARD: [STATUT_EN_COURS, STATUT_ANNULEE],
        STATUT_REPORTEE: [STATUT_PLANIFIEE, STATUT_ANNULEE],
        STATUT_PARTIELLE: [STATUT_EN_COURS, STATUT_EFFECTUEE],
        STATUT_ARCHIVEE: [],
    }

    PERIODICITE_CHOICES = [
        ('hebdomadaire', 'Hebdomadaire'),
        ('mensuelle', 'Mensuelle'),
        ('trimestrielle', 'Trimestrielle'),
        ('semestrielle', 'Semestrielle'),
        ('annuelle', 'Annuelle'),
        ('unique', 'Unique'),
    ]

    equipement = models.ForeignKey(Equipement, on_delete=models.CASCADE, related_name='preventives')
    titre = models.CharField(max_length=300)
    description = models.TextField()
    periodicite = models.CharField(max_length=20, choices=PERIODICITE_CHOICES, default='annuelle')
    date_echeance = models.DateField()
    statut = models.CharField(max_length=30, choices=STATUTS, default=STATUT_PLANIFIEE)
    affecte_a = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='preventives_affectees')
    date_realisation = models.DateField(null=True, blank=True)
    retour_intervention = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='preventives_creees')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date_echeance']
        verbose_name = 'Maintenance préventive'
        verbose_name_plural = 'Maintenances préventives'

    def __str__(self):
        return f"{self.titre} — {self.equipement} (échéance {self.date_echeance})"

    def est_en_retard(self):
        from datetime import date
        return self.date_echeance < date.today() and self.statut not in (
            self.STATUT_EFFECTUEE, self.STATUT_VALIDEE, self.STATUT_ARCHIVEE, self.STATUT_ANNULEE
        )

    def peut_transitionner_vers(self, nouveau_statut):
        return nouveau_statut in self.TRANSITIONS_AUTORISEES.get(self.statut, [])

    def changer_statut(self, nouveau_statut, utilisateur, commentaire=''):
        if not self.peut_transitionner_vers(nouveau_statut):
            raise ValueError(
                f"Transition interdite : {self.statut} → {nouveau_statut}"
            )
        ancien_statut = self.statut
        self.statut = nouveau_statut
        self.save()
        HistoriquePreventive.objects.create(
            preventive=self,
            ancien_statut=ancien_statut,
            nouveau_statut=nouveau_statut,
            modifie_par=utilisateur,
            commentaire=commentaire,
        )
        return self


class HistoriquePreventive(models.Model):
    preventive = models.ForeignKey(MaintenancePreventive, on_delete=models.CASCADE, related_name='historique')
    ancien_statut = models.CharField(max_length=30)
    nouveau_statut = models.CharField(max_length=30)
    modifie_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    commentaire = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        verbose_name = 'Historique préventive'
        verbose_name_plural = 'Historique préventives'


class PreventiveMedia(models.Model):
    preventive = models.ForeignKey(MaintenancePreventive, on_delete=models.CASCADE, related_name='medias')
    fichier = models.FileField(upload_to='preventives/')
    legende = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Média préventive'
        verbose_name_plural = 'Médias préventives'


class Facture(models.Model):
    TYPE_PIECES = 'pieces'
    TYPE_PRESTATION = 'prestation'
    TYPE_LOCATION = 'location'
    TYPE_AUTRE = 'autre'
    TYPES = [
        (TYPE_PIECES, 'Pièces détachées'),
        (TYPE_PRESTATION, 'Prestation externe'),
        (TYPE_LOCATION, 'Location matériel'),
        (TYPE_AUTRE, 'Autre'),
    ]

    STATUT_BROUILLON = 'brouillon'
    STATUT_EMISE = 'emise'
    STATUT_PAYEE = 'payee'
    STATUT_ANNULEE = 'annulee'
    STATUTS = [
        (STATUT_BROUILLON, 'Brouillon'),
        (STATUT_EMISE, 'Émise'),
        (STATUT_PAYEE, 'Payée'),
        (STATUT_ANNULEE, 'Annulée'),
    ]

    panne = models.ForeignKey(Panne, on_delete=models.CASCADE, null=True, blank=True, related_name='factures')
    preventive = models.ForeignKey(MaintenancePreventive, on_delete=models.CASCADE, null=True, blank=True, related_name='factures')
    numero = models.CharField(max_length=50, unique=True)
    fournisseur = models.CharField(max_length=200)
    type_facture = models.CharField(max_length=20, choices=TYPES, default=TYPE_PIECES)
    statut = models.CharField(max_length=20, choices=STATUTS, default=STATUT_BROUILLON)
    montant_ht = models.DecimalField(max_digits=10, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('20.00'))
    montant_tva = models.DecimalField(max_digits=10, decimal_places=2)
    montant_ttc = models.DecimalField(max_digits=10, decimal_places=2)
    date_facture = models.DateField()
    date_echeance_paiement = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    fichier = models.FileField(upload_to='factures/', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='factures_creees')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_facture']
        verbose_name = 'Facture'
        verbose_name_plural = 'Factures'

    def __str__(self):
        return f"Facture {self.numero} — {self.fournisseur} ({self.montant_ttc} €)"

    def clean(self):
        if self.montant_ht is not None and self.montant_tva is not None and self.montant_ttc is not None:
            ttc_calcule = self.montant_ht + self.montant_tva
            if abs(ttc_calcule - self.montant_ttc) > Decimal('0.02'):
                raise ValidationError(
                    f"Incohérence des montants : HT ({self.montant_ht}) + TVA ({self.montant_tva}) "
                    f"= {ttc_calcule} ≠ TTC ({self.montant_ttc})"
                )
        if not self.panne and not self.preventive:
            raise ValidationError("La facture doit être liée à une panne ou à une maintenance préventive.")


class RappelPreventive(models.Model):
    DELAI_J30 = 'j30'
    DELAI_J14 = 'j14'
    DELAI_J7 = 'j7'
    DELAI_J3 = 'j3'
    DELAI_J1 = 'j1'
    DELAI_ECHEANCE = 'j0'
    DELAIS = [
        (DELAI_J30, '30 jours avant'),
        (DELAI_J14, '14 jours avant'),
        (DELAI_J7, '7 jours avant'),
        (DELAI_J3, '3 jours avant'),
        (DELAI_J1, '1 jour avant'),
        (DELAI_ECHEANCE, 'Le jour J'),
    ]

    DELAI_JOURS = {
        DELAI_J30: 30,
        DELAI_J14: 14,
        DELAI_J7: 7,
        DELAI_J3: 3,
        DELAI_J1: 1,
        DELAI_ECHEANCE: 0,
    }

    preventive = models.ForeignKey(
        MaintenancePreventive, on_delete=models.CASCADE, related_name='rappels'
    )
    destinataires = models.ManyToManyField(
        'auth.User', blank=True, related_name='rappels_preventive',
        help_text='Responsables silo à notifier'
    )
    delai = models.CharField(max_length=10, choices=DELAIS, default=DELAI_J7)
    message_personnalise = models.TextField(blank=True)
    envoye_le = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, related_name='rappels_crees'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['delai']
        verbose_name = 'Rappel préventive'
        verbose_name_plural = 'Rappels préventives'

    def __str__(self):
        return f"Rappel {self.get_delai_display()} — {self.preventive.titre}"

    def date_envoi_prevue(self):
        from datetime import timedelta
        jours = self.DELAI_JOURS.get(self.delai, 0)
        return self.preventive.date_echeance - timedelta(days=jours)

    def doit_etre_envoye(self):
        from datetime import date
        return self.envoye_le is None and self.date_envoi_prevue() <= date.today()


class Notification(models.Model):
    TYPE_PANNE = 'panne'
    TYPE_PREVENTIVE = 'preventive'
    TYPE_FACTURE = 'facture'
    TYPE_RETARD = 'retard'
    TYPE_AFFECTATION = 'affectation'
    TYPES = [
        (TYPE_PANNE, 'Panne'),
        (TYPE_PREVENTIVE, 'Maintenance préventive'),
        (TYPE_FACTURE, 'Facture'),
        (TYPE_RETARD, 'Retard'),
        (TYPE_AFFECTATION, 'Affectation'),
    ]

    destinataire = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type_notif = models.CharField(max_length=20, choices=TYPES)
    titre = models.CharField(max_length=300)
    message = models.TextField()
    lue = models.BooleanField(default=False)
    lien = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return f"[{self.destinataire.username}] {self.titre}"
