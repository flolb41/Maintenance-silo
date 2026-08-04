from django.conf import settings
from django.db import models
from django.utils import timezone


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
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SILO)

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
    utilisateurs = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="sites_autorises",
    )

    def __str__(self):
        return self.nom

    class Meta:
        ordering = ["nom"]


class Equipement(models.Model):
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="equipements")
    nom = models.CharField(max_length=150)
    reference = models.CharField(max_length=100, blank=True)
    actif = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nom} ({self.site.nom})"

    class Meta:
        ordering = ["nom"]


# ---------------------------------------------------------------------------
# Pannes
# ---------------------------------------------------------------------------

class Panne(models.Model):
    class Statut(models.TextChoices):
        NOUVELLE = "nouvelle", "Nouvelle"
        AFFECTEE = "affectee", "Affectée"
        EN_COURS = "en_cours", "En cours"
        ATTENTE_PIECE = "attente_piece", "En attente de pièce"
        RESOLUE = "resolue", "Résolue"
        CLOTUREE = "cloturee", "Clôturée"

    class Priorite(models.TextChoices):
        BASSE = "basse", "Basse"
        NORMALE = "normale", "Normale"
        HAUTE = "haute", "Haute"
        CRITIQUE = "critique", "Critique"

    # Transitions autorisées : statut_actuel → [statuts_cibles]
    TRANSITIONS_AUTORISEES = {
        Statut.NOUVELLE: [Statut.AFFECTEE],
        Statut.AFFECTEE: [Statut.EN_COURS, Statut.NOUVELLE],
        Statut.EN_COURS: [Statut.ATTENTE_PIECE, Statut.RESOLUE],
        Statut.ATTENTE_PIECE: [Statut.EN_COURS, Statut.RESOLUE],
        Statut.RESOLUE: [Statut.CLOTUREE, Statut.EN_COURS],
        Statut.CLOTUREE: [],
    }

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="pannes")
    equipement = models.ForeignKey(
        Equipement, on_delete=models.PROTECT, null=True, blank=True, related_name="pannes"
    )
    declarant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pannes_declarees",
    )
    agent_assigne = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pannes_assignees",
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
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.get_statut_display()}] {self.titre}"

    class Meta:
        ordering = ["-creee_le"]


class PanneMedia(models.Model):
    panne = models.ForeignKey(Panne, on_delete=models.CASCADE, related_name="medias")
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
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        ENVOYEE = "envoyee", "Envoyée"
        RECUE = "recue", "Reçue"
        EN_COURS = "en_cours", "En cours"
        A_VALIDER = "a_valider", "À valider"
        VALIDEE = "validee", "Validée"
        REJETEE = "rejetee", "Rejetée"
        EN_RETARD = "en_retard", "En retard"

    # Transitions autorisées : statut_actuel → [statuts_cibles]
    TRANSITIONS_AUTORISEES = {
        Statut.BROUILLON: [Statut.ENVOYEE],
        Statut.ENVOYEE: [Statut.RECUE, Statut.EN_RETARD],
        Statut.RECUE: [Statut.EN_COURS, Statut.EN_RETARD],
        Statut.EN_COURS: [Statut.A_VALIDER],
        Statut.A_VALIDER: [Statut.VALIDEE, Statut.REJETEE],
        Statut.VALIDEE: [],
        Statut.REJETEE: [Statut.ENVOYEE],
        Statut.EN_RETARD: [],
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
    createur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenances_creees",
    )
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenances_recues",
    )
    titre = models.CharField(max_length=200)
    instructions = models.TextField()
    echeance = models.DateTimeField()
    statut = models.CharField(
        max_length=30, choices=Statut.choices, default=Statut.BROUILLON
    )
    retour = models.TextField(blank=True)
    commentaire_validation = models.TextField(blank=True)
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.get_statut_display()}] {self.titre}"

    def est_en_retard(self):
        return self.echeance < timezone.now() and self.statut not in (
            self.Statut.VALIDEE,
            self.Statut.CLOTUREE if hasattr(self.Statut, "CLOTUREE") else "",
        )

    class Meta:
        ordering = ["-creee_le"]


class PreventiveMedia(models.Model):
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
    panne = models.ForeignKey(Panne, on_delete=models.CASCADE, related_name="factures")
    numero = models.CharField(max_length=100)
    fournisseur = models.CharField(max_length=150)
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2)
    montant_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    fichier = models.FileField(upload_to="factures/%Y/%m/", blank=True)
    nom_fichier_original = models.CharField(max_length=255, blank=True)
    validee = models.BooleanField(default=False)
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Facture {self.numero} – {self.fournisseur}"

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
