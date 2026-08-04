"""
Formulaires de l'application maintenance.
Inclut la validation MIME/extension/taille des uploads.
"""
import mimetypes
import os

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import (
    Equipement,
    Facture,
    MaintenancePreventive,
    Panne,
    Site,
)

User = get_user_model()

# MIME types considérés comme sûrs
MIME_TYPES_AUTORISES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "video/mp4",
    "video/webm",
    "video/quicktime",
}


def valider_fichier(fichier):
    """Valide extension, MIME et taille d'un fichier uploadé."""
    if fichier is None:
        return

    # Taille
    max_size = getattr(settings, "MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    if fichier.size > max_size:
        raise ValidationError(
            f"Le fichier est trop volumineux ({fichier.size // 1024} Ko). "
            f"Taille maximale : {max_size // 1024} Ko."
        )

    # Extension
    allowed_exts = getattr(
        settings,
        "ALLOWED_UPLOAD_EXTENSIONS",
        ["jpg", "jpeg", "png", "gif", "pdf", "doc", "docx", "xls", "xlsx", "mp4", "webm", "mov"],
    )
    _, ext = os.path.splitext(fichier.name)
    ext = ext.lstrip(".").lower()
    if ext not in allowed_exts:
        raise ValidationError(
            f"Extension « .{ext} » non autorisée. "
            f"Extensions acceptées : {', '.join(allowed_exts)}."
        )

    # MIME (depuis les premiers octets, pas le nom)
    try:
        import magic

        mime = magic.from_buffer(fichier.read(2048), mime=True)
        fichier.seek(0)
    except Exception:
        # python-magic indisponible : fallback sur mimetypes
        mime, _ = mimetypes.guess_type(fichier.name)

    if mime and mime not in MIME_TYPES_AUTORISES:
        raise ValidationError(
            f"Type MIME « {mime} » non autorisé."
        )


# ---------------------------------------------------------------------------
# Fichier inline (utilisé dans plusieurs formulaires)
# ---------------------------------------------------------------------------

class MediasWidget(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MediasWidget(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        # data peut être une liste de fichiers ou un seul
        if not data and not initial:
            if self.required:
                raise ValidationError(self.error_messages["required"])
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        result = []
        for f in data:
            validated = super().clean(f, initial)
            valider_fichier(validated)
            result.append(validated)
        return result


# ---------------------------------------------------------------------------
# Pannes
# ---------------------------------------------------------------------------

class PanneCreerForm(forms.ModelForm):
    medias = MultipleFileField(label="Fichiers joints", required=False)

    class Meta:
        model = Panne
        fields = ["site", "equipement", "titre", "description", "priorite"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, utilisateur=None, **kwargs):
        super().__init__(*args, **kwargs)
        if utilisateur is not None:
            sites = utilisateur.sites_autorises.filter(actif=True)
            self.fields["site"].queryset = sites
            self.fields["equipement"].queryset = Equipement.objects.filter(
                site__in=sites, actif=True
            )
        self.fields["site"].empty_label = "— Choisir un site —"
        self.fields["equipement"].empty_label = "— Aucun —"
        self.fields["equipement"].required = False


class PanneAffecterForm(forms.ModelForm):
    class Meta:
        model = Panne
        fields = ["agent_assigne"]

    def __init__(self, *args, panne=None, **kwargs):
        super().__init__(*args, **kwargs)
        if panne is not None:
            self.fields["agent_assigne"].queryset = User.objects.filter(
                sites_autorises=panne.site,
                profile__role="maintenance",
            )
        self.fields["agent_assigne"].label = "Agent assigné"


class PanneStatutForm(forms.Form):
    nouveau_statut = forms.ChoiceField(choices=Panne.Statut.choices, label="Nouveau statut")
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Commentaire",
    )
    medias = MultipleFileField(label="Fichiers joints", required=False)


class PanneMediaForm(forms.Form):
    medias = MultipleFileField(label="Fichiers", required=True)


# ---------------------------------------------------------------------------
# Maintenances préventives
# ---------------------------------------------------------------------------

class PreventiveCreerForm(forms.ModelForm):
    medias = MultipleFileField(label="Fichiers joints", required=False)

    class Meta:
        model = MaintenancePreventive
        fields = ["site", "equipement", "destinataire", "titre", "instructions", "echeance"]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "echeance": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, utilisateur=None, **kwargs):
        super().__init__(*args, **kwargs)
        if utilisateur is not None:
            sites = utilisateur.sites_autorises.filter(actif=True)
            self.fields["site"].queryset = sites
            self.fields["equipement"].queryset = Equipement.objects.filter(
                site__in=sites, actif=True
            )
            self.fields["destinataire"].queryset = User.objects.filter(
                sites_autorises__in=sites,
                profile__role="silo",
            ).distinct()
        self.fields["site"].empty_label = "— Choisir un site —"
        self.fields["equipement"].empty_label = "— Aucun —"
        self.fields["destinataire"].empty_label = "— Choisir un agent silo —"
        self.fields["equipement"].required = False


class PreventiveTerminerForm(forms.ModelForm):
    medias = MultipleFileField(label="Photos / documents de clôture", required=False)

    class Meta:
        model = MaintenancePreventive
        fields = ["retour"]
        widgets = {
            "retour": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {"retour": "Compte rendu d'intervention (obligatoire)"}

    def clean_retour(self):
        retour = self.cleaned_data.get("retour", "").strip()
        if not retour:
            raise ValidationError("Le compte rendu est obligatoire pour terminer la tâche.")
        return retour


class PreventiveValiderForm(forms.Form):
    CHOIX = [("valider", "Valider"), ("rejeter", "Rejeter")]
    decision = forms.ChoiceField(choices=CHOIX, widget=forms.RadioSelect, label="Décision")
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Commentaire",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "rejeter" and not cleaned.get("commentaire", "").strip():
            raise ValidationError("Un commentaire est obligatoire pour rejeter une tâche.")
        return cleaned


# ---------------------------------------------------------------------------
# Factures
# ---------------------------------------------------------------------------

class FactureForm(forms.ModelForm):
    fichier_upload = forms.FileField(label="Fichier de facture", required=False)

    class Meta:
        model = Facture
        fields = ["numero", "fournisseur", "montant_ht", "montant_ttc"]

    def clean_fichier_upload(self):
        f = self.cleaned_data.get("fichier_upload")
        if f:
            valider_fichier(f)
        return f

    def clean(self):
        cleaned = super().clean()
        ht = cleaned.get("montant_ht")
        ttc = cleaned.get("montant_ttc")
        if ht is not None and ttc is not None and ttc < ht:
            raise ValidationError("Le montant TTC ne peut pas être inférieur au montant HT.")
        return cleaned
