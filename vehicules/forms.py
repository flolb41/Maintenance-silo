from django import forms

from maintenance.forms import valider_fichier
from maintenance.models import Site

from .models import EntretienVehicule, Vehicule


class VehiculeForm(forms.ModelForm):
    class Meta:
        model = Vehicule
        fields = [
            "site",
            "categorie",
            "immatriculation",
            "marque",
            "modele",
            "numero_serie",
            "carburant",
            "statut",
            "date_mise_circulation",
            "kilometrage",
            "date_assurance",
            "date_controle_technique",
            "date_mines",
            "date_vgp",
            "organisme_vgp",
            "prochain_entretien_date",
            "prochain_entretien_km",
            "photo",
            "notes",
        ]
        widgets = {
            "site": forms.Select(attrs={"class": "form-select"}),
            "categorie": forms.Select(attrs={"class": "form-select"}),
            "immatriculation": forms.TextInput(attrs={"class": "form-control", "placeholder": "AA-123-BB"}),
            "marque": forms.TextInput(attrs={"class": "form-control"}),
            "modele": forms.TextInput(attrs={"class": "form-control"}),
            "numero_serie": forms.TextInput(attrs={"class": "form-control"}),
            "carburant": forms.Select(attrs={"class": "form-select"}),
            "statut": forms.Select(attrs={"class": "form-select"}),
            "date_mise_circulation": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "kilometrage": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "date_assurance": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "date_controle_technique": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "date_mines": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "date_vgp": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "organisme_vgp": forms.TextInput(attrs={"class": "form-control"}),
            "prochain_entretien_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "prochain_entretien_km": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = Site.objects.filter(
            actif=True).order_by("nom")
        self.fields["site"].empty_label = "— Choisir un site —"

    def clean_immatriculation(self):
        return self.cleaned_data["immatriculation"].strip().upper()

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("categorie") == Vehicule.Categorie.POIDS_LOURD
            and not cleaned_data.get("immatriculation")
        ):
            self.add_error(
                "immatriculation", "L'immatriculation est obligatoire pour un poids lourd.")
        if (
            cleaned_data.get(
                "categorie") == Vehicule.Categorie.REMORQUE_POIDS_LOURD
            and not cleaned_data.get("immatriculation")
        ):
            self.add_error(
                "immatriculation", "L'immatriculation est obligatoire pour une remorque poids lourd.")
        if (
            cleaned_data.get(
                "categorie") == Vehicule.Categorie.REMORQUE_POIDS_LOURD
            and not cleaned_data.get("date_mines")
        ):
            self.add_error(
                "date_mines", "La date de passage aux mines est obligatoire pour une remorque poids lourd.")
        if (
            cleaned_data.get(
                "categorie") == Vehicule.Categorie.ENGIN_MANUTENTION
            and not cleaned_data.get("date_vgp")
        ):
            self.add_error(
                "date_vgp", "La date d'échéance VGP est obligatoire pour un engin de manutention.")
        if cleaned_data.get(
                "categorie") == Vehicule.Categorie.ENGIN_MANUTENTION:
            cleaned_data["organisme_vgp"] = "DEKRA"
        return cleaned_data


class EntretienVehiculeForm(forms.ModelForm):
    class Meta:
        model = EntretienVehicule
        fields = [
            "type_entretien",
            "date_entretien",
            "kilometrage",
            "prestataire",
            "description",
            "cout",
            "facture",
        ]
        widgets = {
            "type_entretien": forms.Select(attrs={"class": "form-select"}),
            "date_entretien": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "kilometrage": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "prestataire": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "cout": forms.NumberInput(attrs={"class": "form-control", "min": 0, "step": "0.01"}),
            "facture": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean_facture(self):
        facture = self.cleaned_data.get("facture")
        if facture:
            valider_fichier(facture)
        return facture
