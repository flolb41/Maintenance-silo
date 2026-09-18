"""
Formulaires de l'application maintenance.
Inclut la validation MIME/extension/taille des uploads et les formulaires Django du projet.
"""
import mimetypes
import os
from decimal import Decimal
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.timezone import localdate

try:
    from .facture_extraction import extract_invoice_data_from_document
except ImportError:  # pragma: no cover - module facultatif
    extract_invoice_data_from_document = None

from .models import (
    CelluleGrain,
    Equipement,
    MouvementPiece,
    PieceDetachee,
    Facture,
    MaintenancePreventive,
    Panne,
    Profile,
    ReleveCellule,
    ReleveStockageAPlat,
    Silo,
    Site,
    StockageAPlat,
    TypeGrain,
)

User = get_user_model()


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
    "application/vnd.ms-office",
    "video/mp4",
    "video/webm",
    "video/quicktime",
}


def _detecter_mime_depuis_contenu(data):
    """Détecte le MIME sans dépendre de python-magic."""
    if not data:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        snippet = data[:1024].decode("latin-1", errors="ignore").lower()
        if "word/document.xml" in snippet:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if "xl/workbook.xml" in snippet:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        return "application/vnd.ms-office"
    return None


def _appliquer_alias_form(data, aliases):
    if not data:
        return data
    data = data.copy()
    for ancien, nouveau in aliases.items():
        if ancien in data and nouveau not in data:
            data[nouveau] = data[ancien]
    return data


def valider_fichier(fichier):
    """Valide extension, MIME et taille d'un fichier uploadé."""
    if fichier is None:
        return

    max_size = getattr(settings, "MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    if fichier.size > max_size:
        raise ValidationError(
            f"Le fichier est trop volumineux ({fichier.size // 1024} Ko). "
            f"Taille maximale : {max_size // 1024} Ko."
        )

    allowed_exts = getattr(
        settings,
        "ALLOWED_UPLOAD_EXTENSIONS",
        ["jpg", "jpeg", "png", "gif", "pdf", "doc",
            "docx", "xls", "xlsx", "mp4", "webm", "mov"],
    )
    _, ext = os.path.splitext(fichier.name)
    ext = ext.lstrip(".").lower()
    if ext not in allowed_exts:
        raise ValidationError(
            f"Extension « .{ext} » non autorisée. "
            f"Extensions acceptées : {', '.join(allowed_exts)}."
        )

    fichier.seek(0)
    payload = fichier.read(2048)
    fichier.seek(0)
    mime = _detecter_mime_depuis_contenu(payload)
    if not mime:
        mime, _ = mimetypes.guess_type(fichier.name)

    if mime and mime not in MIME_TYPES_AUTORISES:
        raise ValidationError(f"Type MIME « {mime} » non autorisé.")


def valider_media_terrain(fichier):
    extensions_autorisees = {"jpg", "jpeg", "png",
                             "gif", "webp", "mp4", "webm", "mov"}
    extension = os.path.splitext(fichier.name)[1].lstrip(".").lower()
    if extension not in extensions_autorisees:
        raise ValidationError(
            "Seules les photos et vidéos terrain sont autorisées ici."
        )


def valider_photo(fichier):
    extension = os.path.splitext(fichier.name)[1].lstrip(".").lower()
    if extension not in {"jpg", "jpeg", "png", "gif", "webp"}:
        raise ValidationError(
            "Seules les images JPG, PNG, GIF et WebP sont autorisées.")

    fichier.seek(0)
    mime = _detecter_mime_depuis_contenu(fichier.read(2048))
    fichier.seek(0)
    if mime not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise ValidationError(
            "Le fichier transmis n'est pas une image valide.")


class MediasWidget(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MediasWidget(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        has_data = bool(data)
        has_initial = bool(initial)
        if not has_data and not has_initial:
            if self.required:
                raise ValidationError(self.error_messages["required"])
            return []
        if not isinstance(data, (list, tuple)):
            data = [data] if data else []
        if not data and has_initial:
            if not isinstance(initial, (list, tuple)):
                return [initial]
            return list(initial)
        result = []
        for f in data:
            validated = super().clean(f, None)
            if validated:
                valider_fichier(validated)
                result.append(validated)
        return result


class SiteForm(forms.ModelForm):
    photos = MultipleFileField(
        label="Photos du site",
        required=False,
        widget=MediasWidget(attrs={
            "multiple": True,
            "class": "form-control",
            "accept": "image/jpeg,image/png,image/gif,image/webp",
        }),
    )

    class Meta:
        model = Site
        fields = ["nom", "adresse", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "adresse": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_photos(self):
        photos = self.cleaned_data.get("photos", [])
        for photo in photos:
            valider_photo(photo)
        return photos


class CelluleGrainForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type_grain"].queryset = TypeGrain.objects.filter(
            actif=True)
        self.fields["etat"].required = False
        self.fields["type_grain"].required = False
        self.fields["nombre_toles_hauteur"].required = False

    def clean_nombre_toles_hauteur(self):
        return self.cleaned_data.get("nombre_toles_hauteur") or 15

    def clean(self):
        cleaned_data = super().clean()
        etat = cleaned_data.get("etat") or (
            self.instance.etat
            if self.instance.pk
            else CelluleGrain.Etat.EN_SERVICE
        )
        cleaned_data["etat"] = etat
        if etat == CelluleGrain.Etat.EN_SERVICE:
            if not cleaned_data.get("type_grain"):
                self.add_error(
                    "type_grain",
                    "Sélectionnez le grain stocké dans cette cellule.",
                )
        else:
            cleaned_data["type_grain"] = None
        return cleaned_data

    class Meta:
        model = CelluleGrain
        fields = [
            "silo", "nom", "marque", "etat", "type_grain", "forme", "hauteur_m", "diametre_m",
            "longueur_m", "largeur_m", "nombre_toles_hauteur", "actif",
        ]
        widgets = {
            "silo": forms.Select(attrs={"class": "form-select"}),
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "marque": forms.TextInput(attrs={"class": "form-control"}),
            "etat": forms.Select(attrs={"class": "form-select"}),
            "type_grain": forms.Select(attrs={"class": "form-select"}),
            "forme": forms.Select(attrs={"class": "form-select cellule-forme"}),
            "hauteur_m": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "diametre_m": forms.NumberInput(attrs={"class": "form-control cellule-diametre", "min": "0.01", "step": "0.01"}),
            "longueur_m": forms.NumberInput(attrs={"class": "form-control cellule-longueur", "min": "0.01", "step": "0.01"}),
            "largeur_m": forms.NumberInput(attrs={"class": "form-control cellule-largeur", "min": "0.01", "step": "0.01"}),
            "nombre_toles_hauteur": forms.NumberInput(attrs={"class": "form-control", "min": "1", "step": "1"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SiloSiteForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.initial["actif"] = False

    def has_changed(self):
        if self.instance.pk:
            return super().has_changed()
        if not self.is_bound:
            return False
        return any(
            str(self.data.get(self.add_prefix(nom), "")).strip()
            for nom in ("nom", "description", "actif")
        )

    class Meta:
        model = Silo
        fields = ["nom", "description", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CelluleSiloForm(CelluleGrainForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.initial["forme"] = ""
            self.initial["actif"] = False

    def has_changed(self):
        if self.instance.pk:
            return super().has_changed()
        if not self.is_bound:
            return False
        champs_significatifs = (
            "nom",
            "marque",
            "etat",
            "type_grain",
            "hauteur_m",
            "diametre_m",
            "longueur_m",
            "largeur_m",
            "actif",
        )
        return any(
            str(self.data.get(self.add_prefix(nom), "")).strip()
            for nom in champs_significatifs
        )

    class Meta(CelluleGrainForm.Meta):
        fields = [
            "nom", "marque", "etat", "type_grain", "forme", "hauteur_m", "diametre_m",
            "longueur_m", "largeur_m", "nombre_toles_hauteur", "actif",
        ]


SiloSiteFormSet = forms.inlineformset_factory(
    Site,
    Silo,
    form=SiloSiteForm,
    extra=5,
    can_delete=True,
)


CelluleSiloFormSet = forms.inlineformset_factory(
    Silo,
    CelluleGrain,
    form=CelluleSiloForm,
    extra=1,
    can_delete=True,
)


CelluleSiteLegacyFormSet = forms.inlineformset_factory(
    Site,
    CelluleGrain,
    form=CelluleSiloForm,
    fk_name="site",
    extra=1,
    can_delete=True,
)


class TypeGrainForm(forms.ModelForm):
    class Meta:
        model = TypeGrain
        fields = ["nom", "poids_specifique_moyen", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "poids_specifique_moyen": forms.NumberInput(attrs={
                "class": "form-control", "min": "1", "step": "0.01"
            }),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def save(self, commit=True):
        grain = super().save(commit=commit)
        if commit:
            for cellule in grain.cellules.all():
                cellule.save(update_fields=["capacite_m3", "capacite_tonnes"])
        return grain


class ReleveCelluleForm(forms.ModelForm):
    class Meta:
        model = ReleveCellule
        fields = [
            "tonnage_manuel",
            "nombre_toles_vides",
            "forme_surface",
            "releve_le",
            "commentaire",
        ]
        widgets = {
            "tonnage_manuel": forms.NumberInput(attrs={
                "class": "form-control", "min": "0", "step": "0.01"
            }),
            "nombre_toles_vides": forms.NumberInput(attrs={
                "class": "form-control", "min": "0", "step": "0.25"
            }),
            "forme_surface": forms.Select(attrs={"class": "form-select"}),
            "releve_le": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "commentaire": forms.Textarea(attrs={
                "class": "form-control", "rows": 3
            }),
        }

    def __init__(self, *args, cellule, **kwargs):
        super().__init__(*args, **kwargs)
        self.cellule = cellule
        self.instance.cellule = cellule
        if not self.instance.pk:
            self.instance.type_grain = cellule.type_grain
        self.fields["nombre_toles_vides"].required = False
        self.fields["forme_surface"].required = False
        self.fields["releve_le"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean(self):
        cleaned_data = super().clean()
        if not self.instance.type_grain_id:
            raise ValidationError(
                "Le type de grain doit d'abord être configuré sur la cellule."
            )
        tonnage_manuel = cleaned_data.get("tonnage_manuel")
        nombre_toles_vides = cleaned_data.get("nombre_toles_vides")
        if tonnage_manuel is None and nombre_toles_vides is None:
            raise ValidationError(
                "Saisissez un tonnage manuel ou un nombre de tôles vides."
            )
        if nombre_toles_vides is None:
            cleaned_data["nombre_toles_vides"] = Decimal("0")
        if not cleaned_data.get("forme_surface"):
            cleaned_data["forme_surface"] = ReleveCellule.FormeSurface.AUCUNE
        if nombre_toles_vides is not None:
            if nombre_toles_vides > self.cellule.nombre_toles_hauteur:
                self.add_error(
                    "nombre_toles_vides",
                    f"Cette cellule comporte {self.cellule.nombre_toles_hauteur} tôles.",
                )
            elif nombre_toles_vides % Decimal("0.25"):
                self.add_error(
                    "nombre_toles_vides",
                    "Saisissez le comptage par quart de tôle.",
                )
        return cleaned_data


class StockageAPlatForm(forms.ModelForm):
    class Meta:
        model = StockageAPlat
        fields = ["site", "nom", "type_grain", "actif"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-select"}),
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "type_grain": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, sites=None, **kwargs):
        super().__init__(*args, **kwargs)
        if sites is not None:
            self.fields["site"].queryset = sites
        self.fields["type_grain"].queryset = TypeGrain.objects.filter(
            actif=True)


class ReleveStockageAPlatForm(forms.ModelForm):
    class Meta:
        model = ReleveStockageAPlat
        fields = ["type_grain", "tonnage", "releve_le", "commentaire"]
        widgets = {
            "type_grain": forms.Select(attrs={"class": "form-select"}),
            "tonnage": forms.NumberInput(attrs={
                "class": "form-control", "min": "0", "step": "0.01"
            }),
            "releve_le": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "commentaire": forms.Textarea(attrs={
                "class": "form-control", "rows": 3
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type_grain"].queryset = TypeGrain.objects.filter(
            actif=True)
        self.fields["releve_le"].input_formats = ["%Y-%m-%dT%H:%M"]


class EquipementForm(forms.ModelForm):
    class Meta:
        model = Equipement
        fields = ["site", "equipement_parent", "nom", "reference", "actif"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-select"}),
            "equipement_parent": forms.Select(attrs={"class": "form-select"}),
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "reference": forms.TextInput(attrs={"class": "form-control"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = Site.objects.filter(
            actif=True).order_by("nom")
        self.fields["site"].empty_label = "— Choisir un site —"
        self.fields["equipement_parent"].required = False
        selected_site = None
        if self.data.get("site"):
            selected_site = self.data.get("site")
        elif self.instance and self.instance.pk:
            selected_site = self.instance.site_id
        parents = Equipement.objects.filter(actif=True)
        if selected_site:
            parents = parents.filter(site_id=selected_site)
        if self.instance and self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        parents = parents.select_related("site", "equipement_parent").order_by(
            "site__nom", "nom")
        self.fields["equipement_parent"].queryset = parents
        self.fields["equipement_parent"].empty_label = "— Équipement principal —"
        self.fields["equipement_parent"].help_text = (
            "Choisissez un équipement existant du même site pour créer un sous-équipement."
        )

    def clean(self):
        cleaned_data = super().clean()
        site = cleaned_data.get("site")
        parent = cleaned_data.get("equipement_parent")
        if parent and site and parent.site_id != site.pk:
            self.add_error(
                "equipement_parent",
                "L'équipement parent doit appartenir au même site.",
            )
        if parent and self.instance.pk:
            parent_ids = set()
            current = parent
            while current is not None:
                if current.pk in parent_ids or current.pk == self.instance.pk:
                    self.add_error(
                        "equipement_parent",
                        "La hiérarchie des équipements ne peut pas former de boucle.",
                    )
                    break
                parent_ids.add(current.pk)
                current = current.equipement_parent
        return cleaned_data


class PieceDetacheeForm(forms.ModelForm):
    class Meta:
        model = PieceDetachee
        fields = ["site", "reference", "nom", "stock",
                  "seuil_alerte", "emplacement", "fournisseur", "actif"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control"}),
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "stock": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "seuil_alerte": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "emplacement": forms.TextInput(attrs={"class": "form-control"}),
            "fournisseur": forms.TextInput(attrs={"class": "form-control"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class MouvementPieceForm(forms.ModelForm):
    class Meta:
        model = MouvementPiece
        fields = ["type_mouvement", "quantite", "commentaire"]
        widgets = {
            "type_mouvement": forms.Select(attrs={"class": "form-select"}),
            "quantite": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "commentaire": forms.TextInput(attrs={"class": "form-control"}),
        }


class PanneForm(forms.ModelForm):
    photos = MultipleFileField(
        label="Photos",
        required=False,
        widget=MediasWidget(attrs={
            "multiple": True,
            "class": "form-control",
            "accept": "image/*",
        }),
    )
    videos = MultipleFileField(
        label="Vidéos",
        required=False,
        widget=MediasWidget(attrs={
            "multiple": True,
            "class": "form-control",
            "accept": "video/*,.mov",
        }),
    )

    class Meta:
        model = Panne
        fields = ["site", "equipement", "titre", "description", "priorite"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-select"}),
            "equipement": forms.Select(attrs={"class": "form-select"}),
            "titre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex. Arrêt du convoyeur principal",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": "Décrivez les symptômes observés, leur durée et les conditions de fonctionnement.",
            }),
            "priorite": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_photos(self):
        photos = self.cleaned_data["photos"]
        for photo in photos:
            valider_media_terrain(photo)
        return photos

    def clean_videos(self):
        videos = self.cleaned_data["videos"]
        for video in videos:
            valider_media_terrain(video)
        return videos

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            profile = Profile.objects.filter(user=user).first()
            sites = (
                Site.objects.filter(actif=True)
                if profile and profile.is_admin()
                else user.sites_autorises.filter(actif=True)
            )
            self.fields["site"].queryset = sites
            self.fields["equipement"].queryset = Equipement.objects.filter(
                site__in=sites, actif=True)
        self.fields["site"].empty_label = "— Choisir un site —"
        self.fields["equipement"].empty_label = "— Aucun —"
        self.fields["equipement"].required = False


class PanneCreerForm(PanneForm):
    pass


class PanneAffectationForm(forms.ModelForm):
    class Meta:
        model = Panne
        fields = ["affecte_a"]
        widgets = {
            "affecte_a": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        raw_data = args[0] if args else kwargs.get("data")
        if raw_data is not None:
            data = _appliquer_alias_form(
                raw_data, {"agent_assigne": "affecte_a"})
            if args:
                args = (data, *args[1:])
            else:
                kwargs["data"] = data
        super().__init__(*args, **kwargs)
        self.fields["affecte_a"].queryset = User.objects.filter(
            profile__role=Profile.Role.MAINTENANCE,
        ).order_by("username")
        self.fields["affecte_a"].label = "Agent assigné"


class PannePrioriteForm(forms.ModelForm):
    class Meta:
        model = Panne
        fields = ["priorite"]
        widgets = {
            "priorite": forms.Select(attrs={"class": "form-select"}),
        }


class PanneAffecterForm(PanneAffectationForm):
    pass


class PanneStatutForm(forms.Form):
    nouveau_statut = forms.ChoiceField(
        choices=list(Panne.Statut.choices), label="Nouveau statut")
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Commentaire",
    )
    medias = MultipleFileField(label="Fichiers joints", required=False)

    def __init__(self, *args, panne=None, transitions=None, **kwargs):
        super().__init__(*args, **kwargs)
        if panne is not None:
            if transitions is None:
                transitions = Panne.TRANSITIONS_AUTORISEES.get(
                    panne.statut, [])
            self.fields["nouveau_statut"].choices = [
                (statut, dict(Panne.STATUTS).get(statut, statut))
                for statut in transitions
            ]


class PanneMediaForm(forms.Form):
    medias = MultipleFileField(label="Photos et vidéos terrain", required=True)

    def clean_medias(self):
        medias = self.cleaned_data["medias"]
        for media in medias:
            valider_media_terrain(media)
        return medias


class PanneTempsInterventionForm(forms.Form):
    date_intervention = forms.DateField(
        label="Date d'intervention",
        initial=localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    duree_heures = forms.DecimalField(
        min_value=Decimal("0.02"),
        max_digits=6,
        decimal_places=2,
        label="Durée (heures)",
    )
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Commentaire",
    )

    def __init__(self, *args, **kwargs):
        raw_data = args[0] if args else kwargs.get("data")
        if raw_data is not None and not raw_data.get("duree_heures"):
            duree_minutes = raw_data.get("duree_minutes")
            if duree_minutes:
                data = raw_data.copy()
                data["duree_heures"] = Decimal(duree_minutes) / Decimal(60)
                if args:
                    args = (data, *args[1:])
                else:
                    kwargs["data"] = data
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        duree_heures = cleaned_data.get("duree_heures")
        if duree_heures is not None:
            cleaned_data["duree_minutes"] = max(
                1, int(duree_heures * Decimal(60)))
        return cleaned_data


class PanneFactureUploadForm(forms.Form):
    photos = MultipleFileField(label="Photos / factures", required=False)
    pdfs = MultipleFileField(label="PDF de facture", required=False)

    def clean(self):
        cleaned_data = super().clean()
        fichiers = (
            *cleaned_data.get("photos", []),
            *cleaned_data.get("pdfs", []),
        )
        if not fichiers:
            raise ValidationError(
                "Sélectionnez au moins une facture à importer.")
        max_files = getattr(settings, "MAX_FILES_PER_UPLOAD", 20)
        if len(fichiers) > max_files:
            raise ValidationError(
                f"Vous pouvez importer au maximum {max_files} fichiers à la fois."
            )
        return cleaned_data


class PreventiveCreerForm(forms.ModelForm):
    medias = MultipleFileField(label="Fichiers joints", required=False)

    class Meta:
        model = MaintenancePreventive
        fields = ["site", "equipement", "affecte_a",
                  "titre", "description", "date_echeance"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "date_echeance": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, utilisateur=None, **kwargs):
        raw_data = args[0] if args else kwargs.get("data")
        if raw_data is not None:
            data = _appliquer_alias_form(raw_data, {
                "destinataire": "affecte_a",
                "instructions": "description",
                "echeance": "date_echeance",
            })
            if args:
                args = (data, *args[1:])
            else:
                kwargs["data"] = data
        super().__init__(*args, **kwargs)
        if utilisateur is not None:
            sites = utilisateur.sites_autorises.filter(actif=True)
            self.fields["site"].queryset = sites
            self.fields["equipement"].queryset = Equipement.objects.filter(
                site__in=sites, actif=True)
            self.fields["affecte_a"].queryset = User.objects.filter(
                sites_autorises__in=sites,
                profile__role="silo",
            ).distinct()
        self.fields["site"].empty_label = "— Choisir un site —"
        self.fields["equipement"].empty_label = "— Aucun —"
        self.fields["affecte_a"].empty_label = "— Choisir un agent silo —"
        self.fields["equipement"].required = False


class PreventiveTerminerForm(forms.ModelForm):
    medias = MultipleFileField(
        label="Photos / documents de clôture", required=False)

    class Meta:
        model = MaintenancePreventive
        fields = ["retour_intervention"]
        widgets = {"retour_intervention": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "retour_intervention": "Compte rendu d'intervention (obligatoire)"}

    def clean_retour_intervention(self):
        retour = self.cleaned_data.get("retour_intervention", "").strip()
        if not retour:
            raise ValidationError(
                "Le compte rendu est obligatoire pour terminer la tâche.")
        return retour


class PreventiveValiderForm(forms.Form):
    CHOIX = [("valider", "Valider"), ("rejeter", "Rejeter")]
    decision = forms.ChoiceField(
        choices=CHOIX, widget=forms.RadioSelect, label="Décision")
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Commentaire",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "rejeter" and not cleaned.get("commentaire", "").strip():
            raise ValidationError(
                "Un commentaire est obligatoire pour rejeter une tâche.")
        return cleaned


class MaintenancePreventiveForm(forms.ModelForm):
    class Meta:
        model = MaintenancePreventive
        fields = ["site", "equipement", "affecte_a",
                  "titre", "description", "date_echeance", "periodicite",
                  "recurrence_active", "recurrence_jusquau"]
        widgets = {
            "site": forms.Select(attrs={"class": "form-select"}),
            "equipement": forms.Select(attrs={"class": "form-select"}),
            "affecte_a": forms.Select(attrs={"class": "form-select"}),
            "titre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex. Contrôle mensuel du convoyeur",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 7,
                "placeholder": "Décrivez les contrôles et opérations à réaliser.",
            }),
            "date_echeance": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "periodicite": forms.Select(attrs={"class": "form-select"}),
            "recurrence_active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "recurrence_jusquau": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        raw_data = args[0] if args else kwargs.get("data")
        if raw_data is not None:
            data = _appliquer_alias_form(raw_data, {
                "destinataire": "affecte_a",
                "instructions": "description",
                "echeance": "date_echeance",
            })
            if args:
                args = (data, *args[1:])
            else:
                kwargs["data"] = data
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["recurrence_active"].initial = True
        self.fields["periodicite"].required = False
        self.fields["recurrence_jusquau"].required = False
        if user is not None:
            profile = Profile.objects.filter(user=user).first()
            sites = (
                Site.objects.filter(actif=True)
                if profile and profile.is_admin()
                else user.sites_autorises.filter(actif=True)
            )
            self.fields["site"].queryset = sites
            self.fields["equipement"].queryset = Equipement.objects.filter(
                site__in=sites, actif=True)
            self.fields["affecte_a"].queryset = User.objects.filter(
                sites_autorises__in=sites,
                profile__role="silo",
            ).distinct()
            self.fields["site"].empty_label = "— Choisir un site —"
            self.fields["equipement"].empty_label = "— Aucun équipement —"
            self.fields["affecte_a"].empty_label = "— Choisir un agent silo —"
            self.fields["equipement"].required = False
            self.fields["date_echeance"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean_periodicite(self):
        return (
            self.cleaned_data.get("periodicite")
            or MaintenancePreventive.Periodicite.PONCTUELLE
        )

    def clean(self):
        cleaned_data = super().clean()
        periodicite = cleaned_data.get("periodicite")
        echeance = cleaned_data.get("date_echeance")
        recurrence_jusquau = cleaned_data.get("recurrence_jusquau")

        if periodicite == MaintenancePreventive.Periodicite.PONCTUELLE:
            cleaned_data["recurrence_active"] = False
            cleaned_data["recurrence_jusquau"] = None
        elif recurrence_jusquau and echeance and recurrence_jusquau < echeance.date():
            self.add_error(
                "recurrence_jusquau",
                "La fin de récurrence doit être postérieure à la première échéance.",
            )
        return cleaned_data


class PreventiveStatutForm(forms.Form):
    nouveau_statut = forms.ChoiceField(
        choices=list(MaintenancePreventive.Statut.choices), label="Nouveau statut")
    commentaire = forms.CharField(required=False, widget=forms.Textarea(
        attrs={"rows": 3}), label="Commentaire")
    retour_intervention = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Retour")

    def __init__(self, *args, preventive=None, allowed_statuses=None, status_labels=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_statuses is not None:
            self.fields["nouveau_statut"].choices = [
                (choice, status_labels.get(choice, choice)
                 if status_labels else choice)
                for choice in allowed_statuses
            ]


class FactureForm(forms.ModelForm):
    fichier_upload = forms.FileField(
        label="Fichier à analyser", required=False)

    class Meta:
        model = Facture
        fields = [
            "panne", "numero", "fournisseur", "type_facture",
            "statut", "montant_ht", "taux_tva", "montant_tva", "montant_ttc",
            "date_facture", "description",
        ]
        widgets = {
            "panne": forms.Select(attrs={"class": "form-select"}),
            "numero": forms.TextInput(attrs={"class": "form-control"}),
            "fournisseur": forms.TextInput(attrs={"class": "form-control"}),
            "type_facture": forms.Select(attrs={"class": "form-select"}),
            "statut": forms.Select(attrs={"class": "form-select"}),
            "montant_ht": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "taux_tva": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "montant_tva": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "montant_ttc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "date_facture": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, user=None, panne=None, preventive=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
        self.panne_imposee = panne if isinstance(panne, Panne) else None
        self.fields["panne"].required = self.panne_imposee is None
        self.fields["fichier_upload"].widget.attrs.update({
            "class": "form-control",
            "accept": ".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx",
        })
        if user is not None:
            profile = Profile.objects.filter(user=user).first()
            sites = (
                Site.objects.all()
                if profile and profile.is_admin()
                else user.sites_autorises.all()
            )
            self.fields["panne"].queryset = Panne.objects.filter(
                site__in=sites
            ).select_related("site").order_by("-date_signalement")
        if panne:
            self.fields["panne"].initial = panne
        self.fields["panne"].empty_label = "— Sélectionner la panne concernée —"

    def clean_fichier_upload(self):
        fichier = self.cleaned_data.get("fichier_upload")
        if fichier:
            valider_fichier(fichier)
        return fichier

    def clean(self):
        cleaned = super().clean()
        if self.panne_imposee is not None:
            cleaned["panne"] = self.panne_imposee

        fichier_upload = self.files.get("fichier_upload")
        self.invoice_data = {}
        if fichier_upload and extract_invoice_data_from_document is not None:
            try:
                invoice_data = extract_invoice_data_from_document(
                    fichier_upload) or {}
            except (OSError, TypeError, ValueError):
                invoice_data = {}
            self.invoice_data = invoice_data if isinstance(
                invoice_data, dict) else {}
            if invoice_data:
                if not cleaned.get("numero") and invoice_data.get("numero"):
                    cleaned["numero"] = invoice_data["numero"]
                if not cleaned.get("fournisseur") and invoice_data.get("fournisseur"):
                    cleaned["fournisseur"] = invoice_data["fournisseur"]
                if not cleaned.get("date_facture") and invoice_data.get("date_facture"):
                    cleaned["date_facture"] = invoice_data["date_facture"]
                if cleaned.get("montant_ttc") in (None, "") and invoice_data.get("montant_ttc") is not None:
                    cleaned["montant_ttc"] = Decimal(
                        str(invoice_data["montant_ttc"]))
                for field_name in ("montant_ht", "montant_tva", "taux_tva"):
                    if cleaned.get(field_name) in (None, "") and invoice_data.get(field_name) is not None:
                        cleaned[field_name] = Decimal(
                            str(invoice_data[field_name])
                        )

        if cleaned.get("montant_ht") in (None, ""):
            if cleaned.get("montant_ttc") not in (None, ""):
                cleaned["montant_ht"] = cleaned["montant_ttc"]
            else:
                cleaned["montant_ht"] = Decimal("0.00")
        if cleaned.get("montant_ttc") in (None, ""):
            if cleaned.get("montant_ht") not in (None, ""):
                cleaned["montant_ttc"] = cleaned["montant_ht"]
            else:
                cleaned["montant_ttc"] = Decimal("0.00")

        if cleaned.get("numero") is None or not str(cleaned.get("numero")).strip():
            cleaned["numero"] = f"AUTO-{uuid4().hex[:12].upper()}"
        if cleaned.get("fournisseur") is None or not str(cleaned.get("fournisseur")).strip():
            cleaned["fournisseur"] = "À compléter"

        cleaned["type_facture"] = cleaned.get(
            "type_facture") or Facture.TYPE_AUTRE
        cleaned["statut"] = cleaned.get("statut") or Facture.STATUT_BROUILLON
        cleaned["taux_tva"] = Decimal(str(cleaned.get("taux_tva") or 0))
        cleaned["montant_tva"] = Decimal(str(cleaned.get("montant_tva") or 0))
        if not cleaned.get("panne"):
            self.add_error(
                "panne", "Chaque facture doit être reliée à une panne.")
        return cleaned

    def save(self, commit=True):
        facture = super().save(commit=False)
        facture.preventive = None
        fichier = self.cleaned_data.get("fichier_upload")
        if fichier:
            facture.fichier = fichier
            facture.nom_fichier_original = fichier.name
            detected = getattr(self, "invoice_data", {})
            details = detected.get("_detection", {})
            fallback_complete = all(
                detected.get(field) is not None for field in (
                    "numero", "fournisseur", "date_facture", "montant_ht", "montant_ttc"
                )
            )
            score = int(details.get("score_global",
                        100 if fallback_complete else 0))
            alerts = details.get("alertes", [])
            complete = fallback_complete and score >= 80 and not alerts
            facture.score_detection = max(0, min(100, score))
            facture.details_detection = details
            facture.statut_detection = (
                Facture.DETECTION_OK
                if complete else Facture.DETECTION_INCOMPLETE
            )
        if commit:
            facture.save()
            self.save_m2m()
        return facture

    def clean_montant_ttc(self):
        cleaned = self.cleaned_data
        ht = cleaned.get("montant_ht")
        ttc = cleaned.get("montant_ttc")
        signes_incoherents = (
            ht is not None
            and ttc is not None
            and ht != 0
            and ttc != 0
            and (ht > 0) != (ttc > 0)
        )
        if ht is not None and ttc is not None and (
            signes_incoherents or abs(ttc) < abs(ht)
        ):
            raise ValidationError(
                "Le montant TTC doit être cohérent avec le montant HT.")
        return ttc


class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(
        required=False,
        label="Prénom",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autocomplete": "given-name",
        }),
    )
    last_name = forms.CharField(
        required=False,
        label="Nom",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autocomplete": "family-name",
        }),
    )
    email = forms.EmailField(
        required=False,
        label="Adresse e-mail",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "autocomplete": "email",
            "placeholder": "prenom.nom@entreprise.fr",
        }),
    )

    class Meta:
        model = Profile
        fields = []

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email and User.objects.exclude(
            pk=self.instance.user_id
        ).filter(email__iexact=email).exists():
            raise ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email

    def save(self, user=None, commit=True):
        profile = super().save(commit=False)
        if user is not None:
            user.first_name = self.cleaned_data.get(
                "first_name", user.first_name)
            user.last_name = self.cleaned_data.get("last_name", user.last_name)
            user.email = self.cleaned_data.get("email", user.email)
            user.save(update_fields=["first_name", "last_name", "email"])
        if commit:
            profile.save()
        return profile


class UtilisateurCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput, label="Mot de passe")
    role = forms.ChoiceField(choices=list(Profile.Role.choices), label="Rôle")
    tarif_horaire = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        initial=0,
        label="Tarif horaire (€)",
    )
    sites_autorises = forms.ModelMultipleChoiceField(
        queryset=Site.objects.none(),
        required=False,
        label="Sites autorisés",
        help_text="Obligatoire pour un agent de silo.",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "password"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sites_autorises"].queryset = Site.objects.filter(
            actif=True)

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("role") == Profile.Role.SILO
            and not cleaned_data.get("sites_autorises")
        ):
            self.add_error(
                "sites_autorises",
                "Affectez au moins un site à cet agent de silo.",
            )
        return cleaned_data

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if not user.is_superuser:
            user.is_staff = False
        if commit:
            user.save()
            profile, _ = Profile.objects.get_or_create(
                user=user, defaults={"role": self.cleaned_data["role"]})
            profile.role = self.cleaned_data["role"]
            profile.tarif_horaire = (
                self.cleaned_data.get("tarif_horaire") or Decimal("0.00")
                if profile.is_maintenance()
                else Decimal("0.00")
            )
            profile.save(update_fields=["role", "tarif_horaire"])
            user.sites_autorises.set(
                self.cleaned_data["sites_autorises"]
                if profile.is_silo()
                else []
            )
        return user


class UtilisateurUpdateForm(forms.ModelForm):
    role = forms.ChoiceField(choices=list(Profile.Role.choices),
                             required=False, label="Rôle")
    tarif_horaire = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        label="Tarif horaire (€)",
    )
    sites_autorises = forms.ModelMultipleChoiceField(
        queryset=Site.objects.none(),
        required=False,
        label="Sites autorisés",
        help_text="Obligatoire pour un agent de silo.",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sites_autorises"].queryset = Site.objects.filter(
            actif=True)
        if self.instance and hasattr(self.instance, "profile"):
            self.fields["role"].initial = self.instance.profile.role
            self.fields["tarif_horaire"].initial = self.instance.profile.tarif_horaire
            self.fields["sites_autorises"].initial = self.instance.sites_autorises.filter(
                actif=True
            )

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("role") == Profile.Role.SILO
            and not cleaned_data.get("sites_autorises")
        ):
            self.add_error(
                "sites_autorises",
                "Affectez au moins un site à cet agent de silo.",
            )
        return cleaned_data

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email and User.objects.exclude(pk=self.instance.pk).filter(
            email__iexact=email
        ).exists():
            raise ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.is_superuser:
            user.is_staff = False
        if commit:
            user.save()
            if hasattr(user, "profile"):
                user.profile.role = self.cleaned_data.get(
                    "role", user.profile.role)
                user.profile.tarif_horaire = (
                    self.cleaned_data.get("tarif_horaire") or Decimal("0.00")
                    if user.profile.is_maintenance()
                    else Decimal("0.00")
                )
                user.profile.save(update_fields=["role", "tarif_horaire"])
                user.sites_autorises.set(
                    self.cleaned_data["sites_autorises"]
                    if user.profile.is_silo()
                    else []
                )
        return user


class FacturePdfUploadForm(forms.Form):
    fichier = MultipleFileField(
        label="Fichier(s) de facture", required=True)

    def clean_fichier(self):
        fichiers = self.cleaned_data.get("fichier", [])
        for fichier in fichiers:
            valider_fichier(fichier)
        return fichiers

    def save(self, panne, user):
        fichiers = self.cleaned_data.get("fichier", [])
        factures_creees = []
        for fichier in fichiers:
            invoice_data = {}
            if extract_invoice_data_from_document is not None:
                try:
                    invoice_data = extract_invoice_data_from_document(
                        fichier) or {}
                except (OSError, TypeError, ValueError):
                    invoice_data = {}
            invoice_data = invoice_data if isinstance(
                invoice_data, dict) else {}

            numero = invoice_data.get("numero")
            if not numero:
                numero = f"AUTO-{panne.pk}-{uuid4().hex[:12].upper()}"

            fournisseur = invoice_data.get("fournisseur") or "À compléter"
            date_facture = invoice_data.get("date_facture") or localdate()
            montant_ht = invoice_data.get("montant_ht")
            montant_tva = invoice_data.get("montant_tva")
            taux_tva = invoice_data.get("taux_tva")
            montant_ttc = invoice_data.get("montant_ttc")
            if montant_ttc is None:
                montant_ttc = Decimal("0.00")
            if montant_ht is None:
                montant_ht = montant_ttc
            if montant_tva is None:
                montant_tva = Decimal("0.00")
            if taux_tva is None:
                taux_tva = Decimal("0.00")
            details = invoice_data.get("_detection", {})
            score = int(details.get("score_global", 0))
            complete = score >= 80 and not details.get("alertes")

            facture = Facture.objects.create(
                panne=panne,
                preventive=None,
                numero=numero,
                fournisseur=fournisseur,
                type_facture=Facture.TYPE_AUTRE,
                statut=Facture.STATUT_BROUILLON,
                statut_detection=(
                    Facture.DETECTION_OK if complete
                    else Facture.DETECTION_INCOMPLETE
                ),
                score_detection=score,
                details_detection=details,
                montant_ht=montant_ht,
                taux_tva=taux_tva,
                montant_tva=montant_tva,
                montant_ttc=montant_ttc,
                date_facture=date_facture,
                fichier=fichier,
                nom_fichier_original=fichier.name,
                created_by=user,
            )
            factures_creees.append(facture)
        return factures_creees
