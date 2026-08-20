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
    MaintenancePreventive, HistoriquePreventive, Facture, Notification, Profile,
    RappelPreventive
)
from .forms import (
    SiteForm, EquipementForm, PanneForm, PanneAffectationForm, PanneStatutForm,
    PanneMediaForm, MaintenancePreventiveForm, PreventiveStatutForm,
    FactureForm, ProfileUpdateForm, UtilisateurCreateForm,
    RappelPreventiveForm, StatistiquesFilterForm
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
        try:
            profile = user.profile
        except Exception:
            profile = None
        ctx['profile'] = profile
        if profile and profile.is_admin():
            ctx['factures'] = panne.factures.all()
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
        response = super().form_valid(form)
        fichier = self.request.FILES.get('fichier')
        if fichier:
            PanneMedia.objects.create(
                panne=self.object,
                fichier=fichier,
                legende=self.request.POST.get('legende', ''),
            )
        messages.success(self.request, 'Panne signalée avec succès.')
        return response

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
    try:
        profile = request.user.profile
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if profile.is_silo() and panne.signale_par != request.user:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
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

class PreventiveListView(SiloRequiredMixin, ListView):
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


class PreventiveDetailView(SiloRequiredMixin, DetailView):
    model = MaintenancePreventive
    template_name = 'maintenance/preventive_detail.html'
    context_object_name = 'preventive'

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        try:
            profile = user.profile
        except Exception:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        if profile.is_silo():
            sites = profile.sites.all()
            if obj.equipement.site not in sites:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        preventive = self.object
        user = self.request.user
        try:
            profile = user.profile
        except Exception:
            profile = None
        ctx['profile'] = profile
        ctx['historique'] = preventive.historique.all()
        ctx['medias'] = preventive.medias.all()
        if profile and profile.is_admin():
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

class FactureListView(AdminRequiredMixin, ListView):
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


class FactureDetailView(AdminRequiredMixin, DetailView):
    model = Facture
    template_name = 'maintenance/facture_detail.html'
    context_object_name = 'facture'


class FactureCreateView(AdminRequiredMixin, CreateView):
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


class FactureUpdateView(AdminRequiredMixin, UpdateView):
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


# ─────────────────────────────────────────────
# RAPPELS PRÉVENTIVES (admin seulement)
# ─────────────────────────────────────────────

@login_required
def rappel_create(request, preventive_pk):
    """Créer un rappel sur une maintenance préventive et l'envoyer immédiatement si souhaité."""
    from .signals import creer_notif
    preventive = get_object_or_404(MaintenancePreventive, pk=preventive_pk)
    try:
        if not request.user.profile.is_admin():
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        form = RappelPreventiveForm(request.POST, preventive=preventive)
        if form.is_valid():
            rappel = form.save(commit=False)
            rappel.preventive = preventive
            rappel.created_by = request.user
            rappel.save()
            form.save_m2m()

            # Envoi immédiat si demandé
            if request.POST.get('envoyer_maintenant'):
                destinataires = rappel.destinataires.all()
                if not destinataires.exists():
                    # Fallback : agents silo du site
                    destinataires = preventive.equipement.site.profiles.filter(
                        role='silo'
                    ).values_list('user', flat=True)
                    from django.contrib.auth.models import User as _User
                    destinataires = _User.objects.filter(pk__in=destinataires)

                msg = rappel.message_personnalise or (
                    f"Rappel maintenance préventive : {preventive.titre}\n"
                    f"Équipement : {preventive.equipement}\n"
                    f"Échéance : {preventive.date_echeance}"
                )
                lien = f'/preventives/{preventive.pk}/'
                for user in destinataires:
                    creer_notif(
                        user,
                        Notification.TYPE_PREVENTIVE,
                        f'Rappel préventive : {preventive.titre}',
                        msg,
                        lien,
                    )
                rappel.envoye_le = timezone.now()
                rappel.save(update_fields=['envoye_le'])
                messages.success(request, f'Rappel créé et envoyé à {destinataires.count()} destinataire(s).')
            else:
                messages.success(request, 'Rappel programmé.')
            return redirect('preventive_detail', pk=preventive_pk)
    else:
        form = RappelPreventiveForm(preventive=preventive)

    return render(request, 'maintenance/rappel_form.html', {
        'form': form,
        'preventive': preventive,
    })


@login_required
def rappel_delete(request, pk):
    rappel = get_object_or_404(RappelPreventive, pk=pk)
    try:
        if not request.user.profile.is_admin():
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    prev_pk = rappel.preventive.pk
    rappel.delete()
    messages.success(request, 'Rappel supprimé.')
    return redirect('preventive_detail', pk=prev_pk)


# ─────────────────────────────────────────────
# STATISTIQUES PAR SILO / PÉRIODE (admin seulement)
# ─────────────────────────────────────────────

import csv
from django.http import HttpResponse
from django.db.models import Avg, Sum, FloatField, ExpressionWrapper, F
from django.db.models.functions import Cast


@login_required
def statistiques(request):
    try:
        if not request.user.profile.is_admin():
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
    except Exception:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    form = StatistiquesFilterForm(request.GET or None)
    ctx = {'form': form, 'resultats': None}

    if form.is_valid():
        site_filtre = form.cleaned_data.get('site')
        date_debut = form.cleaned_data.get('date_debut')
        date_fin = form.cleaned_data.get('date_fin')

        sites = Site.objects.all()
        if site_filtre:
            sites = sites.filter(pk=site_filtre.pk)

        resultats = []
        for site in sites:
            # Pannes
            pannes_qs = Panne.objects.filter(equipement__site=site)
            if date_debut:
                pannes_qs = pannes_qs.filter(date_signalement__date__gte=date_debut)
            if date_fin:
                pannes_qs = pannes_qs.filter(date_signalement__date__lte=date_fin)

            pannes_total = pannes_qs.count()
            pannes_resolues = pannes_qs.filter(statut__in=['resolue', 'fermee']).count()
            pannes_critiques = pannes_qs.filter(priorite='critique').count()

            # Durée moyenne résolution (en jours)
            resolues_avec_date = pannes_qs.filter(
                statut__in=['resolue', 'fermee'],
                date_resolution__isnull=False
            )
            duree_moy = None
            if resolues_avec_date.exists():
                total_jours = sum(
                    (p.date_resolution.date() - p.date_signalement.date()).days
                    for p in resolues_avec_date
                )
                duree_moy = round(total_jours / resolues_avec_date.count(), 1)

            # Préventives
            prev_qs = MaintenancePreventive.objects.filter(equipement__site=site)
            if date_debut:
                prev_qs = prev_qs.filter(date_echeance__gte=date_debut)
            if date_fin:
                prev_qs = prev_qs.filter(date_echeance__lte=date_fin)

            prev_total = prev_qs.count()
            prev_effectuees = prev_qs.filter(statut__in=['effectuee', 'validee', 'archivee']).count()
            prev_retard = prev_qs.filter(statut='en_retard').count()
            taux_respect = round(prev_effectuees / prev_total * 100, 1) if prev_total else None

            # Factures
            fact_qs = Facture.objects.filter(
                Q(panne__equipement__site=site) | Q(preventive__equipement__site=site)
            ).distinct()
            if date_debut:
                fact_qs = fact_qs.filter(date_facture__gte=date_debut)
            if date_fin:
                fact_qs = fact_qs.filter(date_facture__lte=date_fin)

            fact_total = fact_qs.count()
            fact_montant_ttc = fact_qs.aggregate(total=Sum('montant_ttc'))['total'] or 0

            resultats.append({
                'site': site,
                'pannes_total': pannes_total,
                'pannes_resolues': pannes_resolues,
                'pannes_critiques': pannes_critiques,
                'duree_moy_resolution': duree_moy,
                'prev_total': prev_total,
                'prev_effectuees': prev_effectuees,
                'prev_retard': prev_retard,
                'taux_respect': taux_respect,
                'fact_total': fact_total,
                'fact_montant_ttc': fact_montant_ttc,
            })

        ctx['resultats'] = resultats
        ctx['date_debut'] = date_debut
        ctx['date_fin'] = date_fin

        # Export CSV
        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="statistiques.csv"'
            response.write('\ufeff')  # BOM pour Excel
            writer = csv.writer(response, delimiter=';')
            writer.writerow([
                'Site', 'Pannes total', 'Pannes résolues', 'Pannes critiques',
                'Durée moy. résolution (j)', 'Préventives total', 'Préventives effectuées',
                'Préventives en retard', 'Taux respect (%)', 'Factures', 'Montant TTC (€)'
            ])
            for r in resultats:
                writer.writerow([
                    r['site'].nom, r['pannes_total'], r['pannes_resolues'],
                    r['pannes_critiques'], r['duree_moy_resolution'] or '',
                    r['prev_total'], r['prev_effectuees'], r['prev_retard'],
                    r['taux_respect'] or '', r['fact_total'], r['fact_montant_ttc'],
                ])
            return response

    return render(request, 'maintenance/statistiques.html', ctx)


# ─────────────────────────────────────────────
# OCR / EXTRACTION FACTURE PDF
# ─────────────────────────────────────────────

import re
import json
import tempfile
import os
from django.views.decorators.http import require_POST


@login_required
@require_POST
def api_extraire_facture(request):
    """
    Reçoit un fichier PDF en POST, extrait les champs clés via pdfplumber
    et retourne un JSON avec fournisseur, date_facture, numero, montant_ttc.
    Un fichier = une facture (potentiellement plusieurs pages).
    """
    try:
        if not request.user.profile.is_admin():
            return HttpResponse(status=403)
    except Exception:
        return HttpResponse(status=403)

    fichier = request.FILES.get('fichier')
    if not fichier:
        return HttpResponse(json.dumps({'error': 'Aucun fichier'}), content_type='application/json', status=400)

    try:
        import pdfplumber
    except ImportError:
        return HttpResponse(
            json.dumps({'error': 'pdfplumber non installé'}),
            content_type='application/json', status=500
        )

    # Écriture temporaire
    suffix = '.pdf'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in fichier.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        texte_complet = ''
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texte_complet += t + '\n'
    finally:
        os.unlink(tmp_path)

    resultat = _extraire_champs_facture(texte_complet)
    return HttpResponse(json.dumps(resultat, ensure_ascii=False), content_type='application/json')


def _extraire_champs_facture(texte):
    """Extrait fournisseur, date, numéro et montant TTC depuis le texte d'une facture."""
    result = {}

    # ── Numéro de facture ──
    patterns_numero = [
        r'(?:facture|invoice|n[o°]\.?\s*facture)[^\d\n]*([A-Z0-9\-/]{4,25})',
        r'(?:ref|réf|reference|référence)[^\d\n]*([A-Z0-9\-/]{4,25})',
        r'\b(FA\s*[-/]?\s*\d{4,})\b',
        r'\b(INV\s*[-/]?\s*\d{4,})\b',
        r'\bN[o°]?\s*:?\s*([A-Z0-9\-/]{5,20})\b',
    ]
    for pat in patterns_numero:
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            result['numero'] = m.group(1).strip().replace(' ', '')
            break

    # ── Date de facture ──
    patterns_date = [
        r'(?:date\s+(?:de\s+)?(?:facture|émission|emission))[^\d\n]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        r'(?:le|date)[^\d\n]{0,10}(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
        r'\b(\d{1,2}-\d{1,2}-\d{4})\b',
        r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b',
    ]
    for pat in patterns_date:
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Normaliser en YYYY-MM-DD
            for sep in ('/', '-', '.'):
                if sep in raw:
                    parts = raw.split(sep)
                    if len(parts) == 3:
                        j, mo, an = parts
                        if len(an) == 2:
                            an = '20' + an
                        try:
                            result['date_facture'] = f"{an}-{mo.zfill(2)}-{j.zfill(2)}"
                        except Exception:
                            pass
                    break
            break

    # ── Montant TTC ──
    patterns_ttc = [
        r'(?:total\s+)?(?:ttc|t\.t\.c\.?|toutes?\s+taxes?\s+comprises?)[\s:]*([0-9\s]+[,\.][0-9]{2})\s*(?:€|eur)?',
        r'(?:net\s+à\s+payer|montant\s+total)[\s:]*([0-9\s]+[,\.][0-9]{2})',
        r'(?:total)[^\d\n]*([0-9\s]{2,10}[,\.][0-9]{2})\s*€',
    ]
    for pat in patterns_ttc:
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().replace(' ', '').replace(',', '.')
            try:
                result['montant_ttc'] = str(round(float(raw), 2))
            except ValueError:
                pass
            break

    # ── Fournisseur : première ligne non vide significative ──
    lignes = [l.strip() for l in texte.split('\n') if l.strip() and len(l.strip()) > 3]
    # Ignorer les lignes qui ressemblent à des dates, numéros, mots-clés
    mots_ignores = re.compile(
        r'^(facture|invoice|bon\s+de\s+commande|devis|date|n[o°]|ref|page|\d)',
        re.IGNORECASE
    )
    for ligne in lignes[:10]:
        if not mots_ignores.match(ligne) and len(ligne) > 4:
            result['fournisseur'] = ligne[:100]
            break

    return result
