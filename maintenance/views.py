from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.db.models import Count, Q
from django.utils import timezone
from datetime import date, timedelta

from .models import (
    Site, Equipement, Panne, HistoriquePanne, PanneMedia,
    MaintenancePreventive, HistoriquePreventive, Facture, Notification, Profile
)
from .forms import (
    SiteForm, EquipementForm, PanneForm, PanneAffectationForm, PanneStatutForm,
    PanneMediaForm, MaintenancePreventiveForm, PreventiveStatutForm,
    FactureForm, ProfileUpdateForm, UtilisateurCreateForm
)
from .mixins import AdminRequiredMixin, MaintenanceRequiredMixin, SiloRequiredMixin, get_sites_utilisateur


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

def connexion(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        next_url = request.GET.get('next', '')
        from django.utils.http import url_has_allowed_host_and_scheme
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('dashboard')
    return render(request, 'maintenance/connexion.html', {'form': form})


@login_required
def deconnexion(request):
    logout(request)
    return redirect('connexion')


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@login_required
def dashboard(request):
    user = request.user
    try:
        profile = user.profile
    except Exception:
        return redirect('connexion')

    sites = get_sites_utilisateur(user)
    ctx = {'profile': profile, 'sites': sites}

    if profile.is_admin():
        pannes = Panne.objects.filter(equipement__site__in=sites)
        preventives = MaintenancePreventive.objects.filter(equipement__site__in=sites)
        factures = Facture.objects.filter(
            Q(panne__equipement__site__in=sites) | Q(preventive__equipement__site__in=sites)
        )
        ctx.update({
            'pannes_nouvelles': pannes.filter(statut='nouvelle').count(),
            'pannes_critiques': pannes.filter(priorite='critique', statut__in=['nouvelle', 'affectee', 'en_cours']).count(),
            'preventives_retard': preventives.filter(date_echeance__lt=date.today(), statut__in=['planifiee', 'en_retard']).count(),
            'factures_en_attente': factures.filter(statut='emise').count(),
            'pannes_recentes': pannes.select_related('equipement__site', 'signale_par').order_by('-created_at')[:5],
            'preventives_prochaines': preventives.filter(
                date_echeance__gte=date.today(),
                date_echeance__lte=date.today() + timedelta(days=30),
                statut='planifiee'
            ).order_by('date_echeance')[:5],
        })

    elif profile.is_maintenance():
        pannes = Panne.objects.filter(equipement__site__in=sites)
        ctx.update({
            'pannes_affectees': pannes.filter(affecte_a=user, statut__in=['affectee', 'en_cours']).count(),
            'pannes_a_affecter': pannes.filter(statut='nouvelle').count(),
            'mes_pannes': pannes.filter(affecte_a=user).order_by('-updated_at')[:5],
            'preventives_dues': MaintenancePreventive.objects.filter(
                equipement__site__in=sites,
                date_echeance__lte=date.today() + timedelta(days=7),
                statut__in=['planifiee', 'en_retard']
            ).order_by('date_echeance')[:5],
        })

    else:  # silo
        pannes = Panne.objects.filter(signale_par=user)
        ctx.update({
            'mes_pannes': pannes.order_by('-created_at')[:5],
            'pannes_ouvertes': pannes.exclude(statut__in=['fermee', 'annulee']).count(),
            'preventives_site': MaintenancePreventive.objects.filter(
                equipement__site__in=sites,
                statut__in=['planifiee', 'en_cours']
            ).order_by('date_echeance')[:5],
        })

    return render(request, 'maintenance/dashboard.html', ctx)


# ─────────────────────────────────────────────
# SITES
# ─────────────────────────────────────────────

class SiteListView(AdminRequiredMixin, ListView):
    model = Site
    template_name = 'maintenance/site_list.html'
    context_object_name = 'sites'


class SiteCreateView(AdminRequiredMixin, CreateView):
    model = Site
    form_class = SiteForm
    template_name = 'maintenance/site_form.html'
    success_url = reverse_lazy('site_list')

    def form_valid(self, form):
        messages.success(self.request, 'Site créé avec succès.')
        return super().form_valid(form)


class SiteUpdateView(AdminRequiredMixin, UpdateView):
    model = Site
    form_class = SiteForm
    template_name = 'maintenance/site_form.html'
    success_url = reverse_lazy('site_list')

    def form_valid(self, form):
        messages.success(self.request, 'Site mis à jour.')
        return super().form_valid(form)


class SiteDeleteView(AdminRequiredMixin, DeleteView):
    model = Site
    template_name = 'maintenance/confirm_delete.html'
    success_url = reverse_lazy('site_list')


# ─────────────────────────────────────────────
# ÉQUIPEMENTS
# ─────────────────────────────────────────────

class EquipementListView(MaintenanceRequiredMixin, ListView):
    model = Equipement
    template_name = 'maintenance/equipement_list.html'
    context_object_name = 'equipements'

    def get_queryset(self):
        sites = get_sites_utilisateur(self.request.user)
        qs = Equipement.objects.filter(site__in=sites).select_related('site')
        site_id = self.request.GET.get('site')
        if site_id:
            qs = qs.filter(site_id=site_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['sites'] = get_sites_utilisateur(self.request.user)
        return ctx


class EquipementCreateView(AdminRequiredMixin, CreateView):
    model = Equipement
    form_class = EquipementForm
    template_name = 'maintenance/equipement_form.html'
    success_url = reverse_lazy('equipement_list')

    def form_valid(self, form):
        messages.success(self.request, 'Équipement créé.')
        return super().form_valid(form)


class EquipementUpdateView(AdminRequiredMixin, UpdateView):
    model = Equipement
    form_class = EquipementForm
    template_name = 'maintenance/equipement_form.html'
    success_url = reverse_lazy('equipement_list')

    def form_valid(self, form):
        messages.success(self.request, 'Équipement mis à jour.')
        return super().form_valid(form)


class EquipementDeleteView(AdminRequiredMixin, DeleteView):
    model = Equipement
    template_name = 'maintenance/confirm_delete.html'
    success_url = reverse_lazy('equipement_list')


# ─────────────────────────────────────────────
# PANNES
# ─────────────────────────────────────────────

class PanneListView(SiloRequiredMixin, ListView):
    model = Panne
    template_name = 'maintenance/panne_list.html'
    context_object_name = 'pannes'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        sites = get_sites_utilisateur(user)
        try:
            profile = user.profile
        except Exception:
            return Panne.objects.none()

        if profile.is_silo():
            qs = Panne.objects.filter(signale_par=user)
        else:
            qs = Panne.objects.filter(equipement__site__in=sites)

        qs = qs.select_related('equipement__site', 'signale_par', 'affecte_a')

        statut = self.request.GET.get('statut')
        priorite = self.request.GET.get('priorite')
        site_id = self.request.GET.get('site')
        q = self.request.GET.get('q')

        if statut:
            qs = qs.filter(statut=statut)
        if priorite:
            qs = qs.filter(priorite=priorite)
        if site_id:
            qs = qs.filter(equipement__site_id=site_id)
        if q:
            qs = qs.filter(Q(titre__icontains=q) | Q(description__icontains=q))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts'] = Panne.STATUTS
        ctx['priorites'] = Panne.PRIORITES
        ctx['sites'] = get_sites_utilisateur(self.request.user)
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_priorite'] = self.request.GET.get('priorite', '')
        ctx['current_site'] = self.request.GET.get('site', '')
        ctx['current_q'] = self.request.GET.get('q', '')
        return ctx


class PanneDetailView(SiloRequiredMixin, DetailView):
    model = Panne
    template_name = 'maintenance/panne_detail.html'
    context_object_name = 'panne'

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        try:
            profile = user.profile
        except Exception:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        if profile.is_silo() and obj.signale_par != user:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        panne = self.object
        user = self.request.user
        ctx['historique'] = panne.historique.all()
        ctx['medias'] = panne.medias.all()
        ctx['factures'] = panne.factures.all()
        try:
            profile = user.profile
        except Exception:
            profile = None
        ctx['profile'] = profile
        if profile and not profile.is_silo():
            ctx['statut_form'] = PanneStatutForm(panne=panne)
            if profile.is_admin() or profile.is_maintenance():
                ctx['affectation_form'] = PanneAffectationForm(instance=panne)
        return ctx


class PanneCreateView(SiloRequiredMixin, CreateView):
    model = Panne
    form_class = PanneForm
    template_name = 'maintenance/panne_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.signale_par = self.request.user
        messages.success(self.request, 'Panne signalée avec succès.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('panne_detail', kwargs={'pk': self.object.pk})


@login_required
def panne_changer_statut(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    try:
        profile = request.user.profile
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if profile.is_silo():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        form = PanneStatutForm(request.POST, panne=panne)
        if form.is_valid():
            try:
                panne.changer_statut(
                    form.cleaned_data['nouveau_statut'],
                    request.user,
                    form.cleaned_data.get('commentaire', ''),
                )
                messages.success(request, 'Statut mis à jour.')
            except ValueError as e:
                messages.error(request, str(e))
    return redirect('panne_detail', pk=pk)


@login_required
def panne_affecter(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    try:
        profile = request.user.profile
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if profile.is_silo():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        form = PanneAffectationForm(request.POST, instance=panne)
        if form.is_valid():
            old_affecte = panne.affecte_a
            panne = form.save(commit=False)
            if panne.statut == Panne.STATUT_NOUVELLE:
                panne.statut = Panne.STATUT_AFFECTEE
                HistoriquePanne.objects.create(
                    panne=panne,
                    ancien_statut=Panne.STATUT_NOUVELLE,
                    nouveau_statut=Panne.STATUT_AFFECTEE,
                    modifie_par=request.user,
                    commentaire='Affectation automatique',
                )
            panne.save()
            messages.success(request, 'Panne affectée.')
    return redirect('panne_detail', pk=pk)


@login_required
def panne_ajouter_media(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    if request.method == 'POST':
        form = PanneMediaForm(request.POST, request.FILES)
        if form.is_valid():
            media = form.save(commit=False)
            media.panne = panne
            media.save()
            messages.success(request, 'Fichier ajouté.')
    return redirect('panne_detail', pk=pk)


# ─────────────────────────────────────────────
# MAINTENANCES PRÉVENTIVES
# ─────────────────────────────────────────────

class PreventiveListView(MaintenanceRequiredMixin, ListView):
    model = MaintenancePreventive
    template_name = 'maintenance/preventive_list.html'
    context_object_name = 'preventives'
    paginate_by = 20

    def get_queryset(self):
        sites = get_sites_utilisateur(self.request.user)
        qs = MaintenancePreventive.objects.filter(
            equipement__site__in=sites
        ).select_related('equipement__site', 'affecte_a')

        statut = self.request.GET.get('statut')
        site_id = self.request.GET.get('site')
        q = self.request.GET.get('q')

        if statut:
            qs = qs.filter(statut=statut)
        if site_id:
            qs = qs.filter(equipement__site_id=site_id)
        if q:
            qs = qs.filter(Q(titre__icontains=q) | Q(description__icontains=q))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts'] = MaintenancePreventive.STATUTS
        ctx['sites'] = get_sites_utilisateur(self.request.user)
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_site'] = self.request.GET.get('site', '')
        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['today'] = date.today()
        return ctx


class PreventiveDetailView(MaintenanceRequiredMixin, DetailView):
    model = MaintenancePreventive
    template_name = 'maintenance/preventive_detail.html'
    context_object_name = 'preventive'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        preventive = self.object
        ctx['historique'] = preventive.historique.all()
        ctx['medias'] = preventive.medias.all()
        ctx['factures'] = preventive.factures.all()
        ctx['statut_form'] = PreventiveStatutForm(preventive=preventive)
        return ctx


class PreventiveCreateView(MaintenanceRequiredMixin, CreateView):
    model = MaintenancePreventive
    form_class = MaintenancePreventiveForm
    template_name = 'maintenance/preventive_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Maintenance préventive planifiée.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('preventive_detail', kwargs={'pk': self.object.pk})


class PreventiveUpdateView(MaintenanceRequiredMixin, UpdateView):
    model = MaintenancePreventive
    form_class = MaintenancePreventiveForm
    template_name = 'maintenance/preventive_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('preventive_detail', kwargs={'pk': self.object.pk})


@login_required
def preventive_changer_statut(request, pk):
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)
    try:
        profile = request.user.profile
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if profile.is_silo():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        form = PreventiveStatutForm(request.POST, preventive=preventive)
        if form.is_valid():
            try:
                preventive.changer_statut(
                    form.cleaned_data['nouveau_statut'],
                    request.user,
                    form.cleaned_data.get('commentaire', ''),
                )
                retour = form.cleaned_data.get('retour_intervention', '')
                if retour:
                    preventive.retour_intervention = retour
                    preventive.save(update_fields=['retour_intervention'])
                messages.success(request, 'Statut mis à jour.')
            except ValueError as e:
                messages.error(request, str(e))
    return redirect('preventive_detail', pk=pk)


# ─────────────────────────────────────────────
# FACTURES
# ─────────────────────────────────────────────

class FactureListView(MaintenanceRequiredMixin, ListView):
    model = Facture
    template_name = 'maintenance/facture_list.html'
    context_object_name = 'factures'
    paginate_by = 20

    def get_queryset(self):
        sites = get_sites_utilisateur(self.request.user)
        qs = Facture.objects.filter(
            Q(panne__equipement__site__in=sites) | Q(preventive__equipement__site__in=sites)
        ).distinct().select_related('panne__equipement', 'preventive__equipement')

        statut = self.request.GET.get('statut')
        type_f = self.request.GET.get('type')
        q = self.request.GET.get('q')

        if statut:
            qs = qs.filter(statut=statut)
        if type_f:
            qs = qs.filter(type_facture=type_f)
        if q:
            qs = qs.filter(Q(numero__icontains=q) | Q(fournisseur__icontains=q))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts'] = Facture.STATUTS
        ctx['types'] = Facture.TYPES
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_type'] = self.request.GET.get('type', '')
        ctx['current_q'] = self.request.GET.get('q', '')
        return ctx


class FactureDetailView(MaintenanceRequiredMixin, DetailView):
    model = Facture
    template_name = 'maintenance/facture_detail.html'
    context_object_name = 'facture'


class FactureCreateView(MaintenanceRequiredMixin, CreateView):
    model = Facture
    form_class = FactureForm
    template_name = 'maintenance/facture_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['panne'] = self.request.GET.get('panne')
        kwargs['preventive'] = self.request.GET.get('preventive')
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        panne_id = self.request.GET.get('panne')
        prev_id = self.request.GET.get('preventive')
        if panne_id:
            initial['panne'] = panne_id
        if prev_id:
            initial['preventive'] = prev_id
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Facture créée.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('facture_detail', kwargs={'pk': self.object.pk})


class FactureUpdateView(MaintenanceRequiredMixin, UpdateView):
    model = Facture
    form_class = FactureForm
    template_name = 'maintenance/facture_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('facture_detail', kwargs={'pk': self.object.pk})


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────

@login_required
def notifications(request):
    notifs = request.user.notifications.order_by('-created_at')
    return render(request, 'maintenance/notifications.html', {'notifs': notifs})


@login_required
def marquer_notif_lue(request, pk):
    notif = get_object_or_404(Notification, pk=pk, destinataire=request.user)
    notif.lue = True
    notif.save(update_fields=['lue'])
    if notif.lien:
        return redirect(notif.lien)
    return redirect('notifications')


@login_required
def marquer_toutes_lues(request):
    request.user.notifications.filter(lue=False).update(lue=True)
    messages.success(request, 'Toutes les notifications ont été marquées comme lues.')
    return redirect('notifications')


# ─────────────────────────────────────────────
# UTILISATEURS (admin seulement)
# ─────────────────────────────────────────────

class UtilisateurListView(AdminRequiredMixin, ListView):
    template_name = 'maintenance/utilisateur_list.html'
    context_object_name = 'utilisateurs'

    def get_queryset(self):
        from django.contrib.auth.models import User
        return User.objects.select_related('profile').order_by('username')


class UtilisateurCreateView(AdminRequiredMixin, CreateView):
    form_class = UtilisateurCreateForm
    template_name = 'maintenance/utilisateur_form.html'
    success_url = reverse_lazy('utilisateur_list')

    def form_valid(self, form):
        messages.success(self.request, 'Utilisateur créé.')
        return super().form_valid(form)


# ─────────────────────────────────────────────
# PROFIL
# ─────────────────────────────────────────────

@login_required
def mon_profil(request):
    try:
        profile = request.user.profile
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save(user=request.user)
            messages.success(request, 'Profil mis à jour.')
            return redirect('mon_profil')
    else:
        form = ProfileUpdateForm(instance=profile, user=request.user)

    return render(request, 'maintenance/mon_profil.html', {'form': form, 'profile': profile})
