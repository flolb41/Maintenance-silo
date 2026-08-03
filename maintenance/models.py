from django.conf import settings
from django.db import models


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
        max_length=20,
        choices=Role.choices,
        default=Role.SILO,
    )

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


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


class Equipement(models.Model):
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="equipements",
    )
    nom = models.CharField(max_length=150)
    reference = models.CharField(max_length=100, blank=True)
    actif = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.site.nom} - {self.nom}"


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

    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="pannes",
    )
    equipement = models.ForeignKey(
        Equipement,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pannes",
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
        max_length=20,
        choices=Priorite.choices,
        default=Priorite.NORMALE,
    )
    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.NOUVELLE,
    )
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.titre


class PanneMedia(models.Model):
    panne = models.ForeignKey(
        Panne,
        on_delete=models.CASCADE,
        related_name="medias",
    )
    fichier = models.FileField(upload_to="pannes/%Y/%m/")
    ajoute_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    cree_le = models.DateTimeField(auto_now_add=True)


class MaintenancePreventive(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        ENVOYEE = "envoyee", "Envoyée"
        EN_COURS = "en_cours", "En cours"
        A_VALIDER = "a_valider", "À valider"
        VALIDEE = "validee", "Validée"
        REJETEE = "rejetee", "Rejetée"
        EN_RETARD = "en_retard", "En retard"

    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="maintenances_preventives",
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
        max_length=30,
        choices=Statut.choices,
        default=Statut.BROUILLON,
    )
    retour = models.TextField(blank=True)
    creee_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre


class Facture(models.Model):
    panne = models.ForeignKey(
        Panne,
        on_delete=models.CASCADE,
        related_name="factures",
    )
    numero = models.CharField(max_length=100)
    fournisseur = models.CharField(max_length=150)
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2)
    montant_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    fichier = models.FileField(upload_to="factures/%Y/%m/", blank=True)
    validee = models.BooleanField(default=False)
    creee_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.numero} - {self.fournisseur}"


class Notification(models.Model):
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    titre = models.CharField(max_length=200)
    message = models.TextField()
    lue = models.BooleanField(default=False)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]

    def __str__(self):
        return self.titre
