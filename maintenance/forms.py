from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from decimal import Decimal
from .models import (
    Site, Equipement, Panne, PanneMedia, MaintenancePreventive,
    PreventiveMedia, Facture, Profile
)


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ['nom', 'adresse', 'description']
        widgets = {
            'adresse': forms.Textarea(attrs={'rows': 3}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class EquipementForm(forms.ModelForm):
    class Meta:
        model = Equipement
        fields = ['site', 'nom', 'reference', 'categorie', 'description', 'date_installation', 'actif']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'date_installation': forms.DateInput(attrs={'type': 'date'}),
        }


class PanneForm(forms.ModelForm):
    class Meta:
        model = Panne
        fields = ['equipement', 'titre', 'description', 'priorite']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.profile.is_admin():
            sites = user.profile.sites.all()
            self.fields['equipement'].queryset = Equipement.objects.filter(site__in=sites, actif=True)


class PanneAffectationForm(forms.ModelForm):
    class Meta:
        model = Panne
        fields = ['affecte_a']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['affecte_a'].queryset = User.objects.filter(
            profile__role='maintenance'
        ).select_related('profile')
        self.fields['affecte_a'].label = 'Affecter à'


class PanneStatutForm(forms.Form):
    nouveau_statut = forms.ChoiceField(choices=[], label='Nouveau statut')
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Commentaire',
    )

    def __init__(self, *args, panne=None, **kwargs):
        super().__init__(*args, **kwargs)
        if panne:
            transitions = panne.TRANSITIONS_AUTORISEES.get(panne.statut, [])
            labels = dict(panne.STATUTS)
            self.fields['nouveau_statut'].choices = [
                (s, labels[s]) for s in transitions
            ]


class PanneMediaForm(forms.ModelForm):
    class Meta:
        model = PanneMedia
        fields = ['fichier', 'legende']


class MaintenancePreventiveForm(forms.ModelForm):
    class Meta:
        model = MaintenancePreventive
        fields = ['equipement', 'titre', 'description', 'periodicite', 'date_echeance', 'affecte_a']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'date_echeance': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.profile.is_admin():
            sites = user.profile.sites.all()
            self.fields['equipement'].queryset = Equipement.objects.filter(site__in=sites, actif=True)
        self.fields['affecte_a'].queryset = User.objects.filter(
            profile__role='maintenance'
        ).select_related('profile')
        self.fields['affecte_a'].required = False


class PreventiveStatutForm(forms.Form):
    nouveau_statut = forms.ChoiceField(choices=[], label='Nouveau statut')
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Commentaire',
    )
    retour_intervention = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Retour d\'intervention',
    )

    def __init__(self, *args, preventive=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preventive:
            transitions = preventive.TRANSITIONS_AUTORISEES.get(preventive.statut, [])
            labels = dict(preventive.STATUTS)
            self.fields['nouveau_statut'].choices = [
                (s, labels[s]) for s in transitions
            ]


class FactureForm(forms.ModelForm):
    class Meta:
        model = Facture
        fields = [
            'numero', 'fournisseur', 'type_facture', 'statut',
            'montant_ht', 'taux_tva', 'montant_tva', 'montant_ttc',
            'date_facture', 'date_echeance_paiement', 'description', 'fichier',
            'panne', 'preventive',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'date_facture': forms.DateInput(attrs={'type': 'date'}),
            'date_echeance_paiement': forms.DateInput(attrs={'type': 'date'}),
            'montant_ht': forms.NumberInput(attrs={'step': '0.01'}),
            'montant_tva': forms.NumberInput(attrs={'step': '0.01'}),
            'montant_ttc': forms.NumberInput(attrs={'step': '0.01'}),
        }

    def __init__(self, *args, user=None, panne=None, preventive=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['panne'].required = False
        self.fields['preventive'].required = False
        if panne:
            self.fields['panne'].initial = panne
        if preventive:
            self.fields['preventive'].initial = preventive
        if user and not user.profile.is_admin():
            sites = user.profile.sites.all()
            self.fields['panne'].queryset = Panne.objects.filter(
                equipement__site__in=sites
            )
            self.fields['preventive'].queryset = MaintenancePreventive.objects.filter(
                equipement__site__in=sites
            )

    def clean(self):
        cleaned_data = super().clean()
        ht = cleaned_data.get('montant_ht')
        tva = cleaned_data.get('montant_tva')
        ttc = cleaned_data.get('montant_ttc')
        panne = cleaned_data.get('panne')
        preventive = cleaned_data.get('preventive')

        if not panne and not preventive:
            raise forms.ValidationError(
                "La facture doit être liée à une panne ou à une maintenance préventive."
            )

        if ht is not None and tva is not None and ttc is not None:
            if abs((ht + tva) - ttc) > Decimal('0.02'):
                raise forms.ValidationError(
                    f"Incohérence : HT ({ht}) + TVA ({tva}) = {ht + tva} ≠ TTC ({ttc})"
                )
        return cleaned_data


class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, label='Prénom', required=False)
    last_name = forms.CharField(max_length=150, label='Nom', required=False)
    email = forms.EmailField(label='Email', required=False)

    class Meta:
        model = Profile
        fields = ['telephone']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email

    def save(self, user=None, commit=True):
        profile = super().save(commit=False)
        if user:
            user.first_name = self.cleaned_data['first_name']
            user.last_name = self.cleaned_data['last_name']
            user.email = self.cleaned_data['email']
            if commit:
                user.save()
        if commit:
            profile.save()
        return profile


class UtilisateurCreateForm(UserCreationForm):
    role = forms.ChoiceField(choices=Profile.ROLES, label='Rôle')
    sites = forms.ModelMultipleChoiceField(
        queryset=Site.objects.all(),
        required=False,
        label='Sites autorisés',
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password1', 'password2']

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.sites.set(self.cleaned_data['sites'])
            profile.save()
        return user


def _add_bootstrap_classes(form):
    """Injecte les classes Bootstrap sur tous les widgets du formulaire."""
    for field in form.fields.values():
        widget = field.widget
        css = widget.attrs.get('class', '')
        if hasattr(widget, 'input_type'):
            if widget.input_type in ('text', 'email', 'password', 'number', 'date', 'tel', 'url', 'file'):
                widget.attrs['class'] = (css + ' form-control').strip()
            elif widget.input_type == 'select':
                widget.attrs['class'] = (css + ' form-select').strip()
            elif widget.input_type == 'checkbox':
                widget.attrs['class'] = (css + ' form-check-input').strip()
        elif isinstance(widget, forms.Textarea):
            widget.attrs['class'] = (css + ' form-control').strip()
        elif isinstance(widget, forms.Select):
            widget.attrs['class'] = (css + ' form-select').strip()
        elif isinstance(widget, forms.CheckboxSelectMultiple):
            pass  # Bootstrap checkbox list rendered manually
        elif isinstance(widget, forms.FileInput):
            widget.attrs['class'] = (css + ' form-control').strip()


# Patch all form __init__ methods to add Bootstrap classes

_originals = {}

for _FormClass in [
    SiteForm, EquipementForm, PanneForm, PanneAffectationForm,
    MaintenancePreventiveForm, FactureForm, ProfileUpdateForm, UtilisateurCreateForm
]:
    _orig = _FormClass.__init__

    def _make_init(orig_init):
        def _new_init(self, *args, **kwargs):
            orig_init(self, *args, **kwargs)
            _add_bootstrap_classes(self)
        return _new_init

    _FormClass.__init__ = _make_init(_orig)
