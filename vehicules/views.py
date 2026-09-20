from django.contrib import messages
from django.db.models import Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils.timezone import localdate
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from maintenance.mixins import AdminRequiredMixin
from maintenance.models import Site

from .forms import EntretienVehiculeForm, VehiculeForm
from .models import EntretienVehicule, Vehicule


CATEGORIES_GEREES = (
    Vehicule.Categorie.POIDS_LOURD,
    Vehicule.Categorie.ENGIN_MANUTENTION,
    Vehicule.Categorie.REMORQUE_POIDS_LOURD,
)


class VehiculeListView(AdminRequiredMixin, ListView):
    model = Vehicule
    template_name = "vehicules/vehicule_list.html"
    context_object_name = "vehicules"

    def get_queryset(self):
        queryset = Vehicule.objects.filter(
            categorie__in=CATEGORIES_GEREES
        ).exclude(
            statut=Vehicule.Statut.CEDE
        ).select_related("site")
        recherche = self.request.GET.get("q", "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(immatriculation__icontains=recherche)
                | Q(marque__icontains=recherche)
                | Q(modele__icontains=recherche)
                | Q(numero_serie__icontains=recherche)
            )
        for champ in ("categorie", "statut", "site"):
            valeur = self.request.GET.get(champ)
            if valeur:
                queryset = queryset.filter(**{champ: valeur})
        return queryset

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        parc = Vehicule.objects.filter(
            categorie__in=CATEGORIES_GEREES
        ).exclude(statut=Vehicule.Statut.CEDE)
        contexte.update({
            "total_vehicules": parc.count(),
            "total_pl": parc.filter(
                categorie=Vehicule.Categorie.POIDS_LOURD
            ).count(),
            "total_engins": parc.filter(
                categorie=Vehicule.Categorie.ENGIN_MANUTENTION
            ).count(),
            "total_remorques": parc.filter(
                categorie=Vehicule.Categorie.REMORQUE_POIDS_LOURD
            ).count(),
            "alertes": sum(1 for vehicule in parc if vehicule.alerte_echeance),
            "categories": Vehicule.Categorie.choices,
            "statuts": Vehicule.Statut.choices,
            "sites": Site.objects.filter(
                actif=True,
                activite_vehicules=True,
            ).order_by("nom"),
            "current_q": self.request.GET.get("q", ""),
            "current_categorie": self.request.GET.get("categorie", ""),
            "current_statut": self.request.GET.get("statut", ""),
            "current_site": self.request.GET.get("site", ""),
        })
        return contexte


class VehiculeDetailView(AdminRequiredMixin, DetailView):
    model = Vehicule
    template_name = "vehicules/vehicule_detail.html"
    context_object_name = "vehicule"

    def get_queryset(self):
        return Vehicule.objects.filter(
            categorie__in=CATEGORIES_GEREES
        ).select_related("site", "cree_par").prefetch_related("entretiens")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["entretiens"] = self.object.entretiens.select_related(
            "cree_par")
        contexte["cout_total"] = self.object.entretiens.aggregate(total=Sum("cout"))[
            "total"] or 0
        contexte["today"] = localdate()
        return contexte


class VehiculeCreateView(AdminRequiredMixin, CreateView):
    model = Vehicule
    form_class = VehiculeForm
    template_name = "vehicules/vehicule_form.html"

    def form_valid(self, form):
        form.instance.cree_par = self.request.user
        messages.success(self.request, "Véhicule ajouté au parc.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("vehicules:detail", kwargs={"pk": self.object.pk})


class VehiculeUpdateView(AdminRequiredMixin, UpdateView):
    model = Vehicule
    form_class = VehiculeForm
    template_name = "vehicules/vehicule_form.html"

    def get_queryset(self):
        return Vehicule.objects.filter(categorie__in=CATEGORIES_GEREES)

    def form_valid(self, form):
        messages.success(self.request, "Fiche véhicule mise à jour.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("vehicules:detail", kwargs={"pk": self.object.pk})


class VehiculeDeleteView(AdminRequiredMixin, DeleteView):
    model = Vehicule
    template_name = "maintenance/confirm_delete.html"
    success_url = reverse_lazy("vehicules:liste")

    def get_queryset(self):
        return Vehicule.objects.filter(categorie__in=CATEGORIES_GEREES)

    def form_valid(self, form):
        if self.object.photo:
            self.object.photo.delete(save=False)
        if self.object.rapport_vgp:
            self.object.rapport_vgp.delete(save=False)
        for entretien in self.object.entretiens.all():
            if entretien.facture:
                entretien.facture.delete(save=False)
        messages.success(self.request, "Véhicule supprimé du parc.")
        return super().form_valid(form)


class EntretienCreateView(AdminRequiredMixin, CreateView):
    model = EntretienVehicule
    form_class = EntretienVehiculeForm
    template_name = "vehicules/entretien_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.vehicule = get_object_or_404(
            Vehicule,
            pk=kwargs["vehicule_pk"],
            categorie__in=CATEGORIES_GEREES,
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.vehicule = self.vehicule
        form.instance.cree_par = self.request.user
        mise_a_jour = []
        if form.cleaned_data["kilometrage"] > self.vehicule.kilometrage:
            self.vehicule.kilometrage = form.cleaned_data["kilometrage"]
            mise_a_jour.append("kilometrage")
        if form.cleaned_data["type_entretien"] == EntretienVehicule.TypeEntretien.REVISION:
            self.vehicule.planifier_prochaine_revision(
                form.cleaned_data["date_entretien"],
                form.cleaned_data["kilometrage"],
            )
            if self.vehicule.periodicite_revision_mois:
                mise_a_jour.append("prochain_entretien_date")
            if self.vehicule.periodicite_revision_km:
                mise_a_jour.append("prochain_entretien_km")
        if mise_a_jour:
            self.vehicule.save(update_fields=[*mise_a_jour, "modifie_le"])
        messages.success(self.request, "Entretien enregistré.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["vehicule"] = self.vehicule
        return contexte

    def get_success_url(self):
        return reverse("vehicules:detail", kwargs={"pk": self.vehicule.pk})


class EntretienDeleteView(AdminRequiredMixin, DeleteView):
    model = EntretienVehicule
    template_name = "maintenance/confirm_delete.html"

    def form_valid(self, form):
        if self.object.facture:
            self.object.facture.delete(save=False)
        messages.success(self.request, "Entretien supprimé.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("vehicules:detail", kwargs={"pk": self.object.vehicule_id})


class VehiculePhotoView(AdminRequiredMixin, DetailView):
    model = Vehicule

    def get_queryset(self):
        return Vehicule.objects.filter(categorie__in=CATEGORIES_GEREES)

    def get(self, request, *args, **kwargs):
        vehicule = self.get_object()
        if not vehicule.photo:
            raise Http404
        return FileResponse(vehicule.photo.open("rb"), as_attachment=False)


class EntretienFactureView(AdminRequiredMixin, DetailView):
    model = EntretienVehicule

    def get(self, request, *args, **kwargs):
        entretien = self.get_object()
        if not entretien.facture:
            raise Http404
        return FileResponse(
            entretien.facture.open("rb"),
            as_attachment=True,
            filename=entretien.facture.name.rsplit("/", 1)[-1],
        )


class VehiculeRapportVgpView(AdminRequiredMixin, DetailView):
    model = Vehicule

    def get_queryset(self):
        return Vehicule.objects.filter(categorie__in=CATEGORIES_GEREES)

    def get(self, request, *args, **kwargs):
        vehicule = self.get_object()
        if not vehicule.rapport_vgp:
            raise Http404
        return FileResponse(
            vehicule.rapport_vgp.open("rb"),
            as_attachment=True,
            filename=vehicule.rapport_vgp.name.rsplit("/", 1)[-1],
        )
