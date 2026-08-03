"""
Vues de l'application maintenance.
Toutes les vues exigent l'authentification et appliquent les permissions
par rôle et par site.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from .forms import (
    FactureForm,
    MultipleFileField,
    PanneAffecterForm,
    PanneCreerForm,
    PanneMediaForm,
    PanneStatutForm,
    PreventiveCreerForm,
    PreventiveTerminerForm,
    PreventiveValiderForm,
)
from .models import (
    Equipement,
    Facture,
    MaintenancePreventive,
    Notification,
    Panne,
    PanneMedia,
    PreventiveMedia,
    Site,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_profile(request):
    """Retourne le profil de l'utilisateur connecté."""
    try:
        return request.user.profile
    except Exception:
        raise PermissionDenied("Aucun profil défini pour cet utilisateur.")


def _sites_autorises(user):
    return user.sites_autorises.filter(actif=True)


def _sauvegarder_medias_panne(files, panne, user):
    for f in files:
        PanneMedia.objects.create(
            panne=panne,
            fichier=f,
            nom_original=f.name,
            ajoute_par=user,
        )


def _sauvegarder_medias_preventive(files, preventive, user):
    for f in files:
        PreventiveMedia.objects.create(
            preventive=preventive,
            fichier=f,
            nom_original=f.name,
            ajoute_par=user,
        )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)
    ctx = {"profile": profile, "sites": sites}

    if profile.is_admin():
        ctx["pannes_ouvertes"] = Panne.objects.filter(
            site__in=sites
        ).exclude(statut=Panne.Statut.CLOTUREE).count()
        ctx["pannes_critiques"] = Panne.objects.filter(
            site__in=sites, priorite=Panne.Priorite.CRITIQUE
        ).exclude(statut=Panne.Statut.CLOTUREE).count()
        ctx["preventives_retard"] = MaintenancePreventive.objects.filter(
            site__in=sites, statut=MaintenancePreventive.Statut.EN_RETARD
        ).count()
        ctx["factures_non_validees"] = Facture.objects.filter(
            panne__site__in=sites, validee=False
        ).count()
        ctx["pannes_recentes"] = Panne.objects.filter(site__in=sites).select_related(
            "site", "declarant", "agent_assigne"
        )[:10]
        ctx["preventives_recentes"] = MaintenancePreventive.objects.filter(
            site__in=sites
        ).select_related("site", "createur", "destinataire")[:10]

    elif profile.is_maintenance():
        ctx["pannes_a_affecter"] = Panne.objects.filter(
            site__in=sites, statut=Panne.Statut.NOUVELLE
        ).count()
        ctx["pannes_assignees"] = Panne.objects.filter(
            site__in=sites, agent_assigne=request.user
        ).exclude(statut=Panne.Statut.CLOTUREE).count()
        ctx["preventives_a_valider"] = MaintenancePreventive.objects.filter(
            site__in=sites,
            createur=request.user,
            statut=MaintenancePreventive.Statut.A_VALIDER,
        ).count()
        ctx["pannes_recentes"] = Panne.objects.filter(site__in=sites).select_related(
            "site", "declarant", "agent_assigne"
        )[:10]
        ctx["preventives_recentes"] = MaintenancePreventive.objects.filter(
            site__in=sites, createur=request.user
        ).select_related("site", "destinataire")[:10]

    elif profile.is_silo():
        ctx["pannes_declarees"] = Panne.objects.filter(
            site__in=sites, declarant=request.user
        ).count()
        ctx["taches_recues"] = MaintenancePreventive.objects.filter(
            destinataire=request.user,
            statut__in=[
                MaintenancePreventive.Statut.ENVOYEE,
                MaintenancePreventive.Statut.RECUE,
            ],
        ).count()
        ctx["taches_en_cours"] = MaintenancePreventive.objects.filter(
            destinataire=request.user,
            statut=MaintenancePreventive.Statut.EN_COURS,
        ).count()
        ctx["pannes_recentes"] = Panne.objects.filter(
            site__in=sites, declarant=request.user
        ).select_related("site")[:10]
        ctx["preventives_recentes"] = MaintenancePreventive.objects.filter(
            destinataire=request.user
        ).select_related("site", "createur")[:10]

    ctx["notifications_non_lues"] = Notification.objects.filter(
        utilisateur=request.user, lue=False
    ).count()
    return render(request, "maintenance/dashboard.html", ctx)


# ---------------------------------------------------------------------------
# Pannes – liste
# ---------------------------------------------------------------------------

@login_required
def panne_liste(request):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)

    if profile.is_silo():
        qs = Panne.objects.filter(site__in=sites, declarant=request.user)
    elif profile.is_maintenance():
        qs = Panne.objects.filter(
            Q(site__in=sites)
        )
    else:  # admin
        qs = Panne.objects.filter(site__in=sites)

    qs = qs.select_related("site", "equipement", "declarant", "agent_assigne").order_by(
        "-creee_le"
    )
    return render(request, "maintenance/panne_liste.html", {"pannes": qs, "profile": profile})


# ---------------------------------------------------------------------------
# Pannes – détail
# ---------------------------------------------------------------------------

@login_required
def panne_detail(request, pk):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)
    panne = get_object_or_404(Panne, pk=pk)

    if panne.site not in sites:
        raise PermissionDenied

    # Agent silo : uniquement les pannes qu'il a déclarées
    if profile.is_silo() and panne.declarant != request.user:
        raise PermissionDenied

    medias = panne.medias.all()
    factures = panne.factures.all()
    affectation_form = None
    statut_form = None
    media_form = None
    facture_form = None

    if profile.is_admin() or profile.is_maintenance():
        affectation_form = PanneAffecterForm(panne=panne)
        statut_form = PanneStatutForm()
        media_form = PanneMediaForm()
        facture_form = FactureForm()

    ctx = {
        "panne": panne,
        "medias": medias,
        "factures": factures,
        "profile": profile,
        "affectation_form": affectation_form,
        "statut_form": statut_form,
        "media_form": media_form,
        "facture_form": facture_form,
        "transitions_autorisees": Panne.TRANSITIONS_AUTORISEES.get(panne.statut, []),
    }
    return render(request, "maintenance/panne_detail.html", ctx)


# ---------------------------------------------------------------------------
# Pannes – création
# ---------------------------------------------------------------------------

@login_required
def panne_creer(request):
    profile = _get_profile(request)
    if request.method == "POST":
        form = PanneCreerForm(request.POST, request.FILES, utilisateur=request.user)
        if form.is_valid():
            panne = form.save(commit=False)
            panne.declarant = request.user
            panne.save()
            fichiers = request.FILES.getlist("medias")
            _sauvegarder_medias_panne(fichiers, panne, request.user)
            messages.success(request, "Panne déclarée avec succès.")
            return redirect("panne_detail", pk=panne.pk)
    else:
        form = PanneCreerForm(utilisateur=request.user)
    return render(request, "maintenance/panne_form.html", {"form": form, "profile": profile})


# ---------------------------------------------------------------------------
# Pannes – affecter
# ---------------------------------------------------------------------------

@login_required
def panne_affecter(request, pk):
    profile = _get_profile(request)
    if not (profile.is_admin() or profile.is_maintenance()):
        raise PermissionDenied

    sites = _sites_autorises(request.user)
    panne = get_object_or_404(Panne, pk=pk, site__in=sites)

    if request.method == "POST":
        form = PanneAffecterForm(request.POST, instance=panne, panne=panne)
        if form.is_valid():
            panne = form.save(commit=False)
            panne.statut = Panne.Statut.AFFECTEE
            panne.save()
            messages.success(request, "Panne affectée.")
            return redirect("panne_detail", pk=panne.pk)
    else:
        form = PanneAffecterForm(instance=panne, panne=panne)
    return render(
        request,
        "maintenance/panne_affecter.html",
        {"form": form, "panne": panne, "profile": profile},
    )


# ---------------------------------------------------------------------------
# Pannes – changer statut
# ---------------------------------------------------------------------------

@login_required
def panne_changer_statut(request, pk):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)
    panne = get_object_or_404(Panne, pk=pk, site__in=sites)

    if profile.is_silo():
        raise PermissionDenied

    if request.method == "POST":
        form = PanneStatutForm(request.POST, request.FILES)
        if form.is_valid():
            nouveau = form.cleaned_data["nouveau_statut"]
            transitions = Panne.TRANSITIONS_AUTORISEES.get(panne.statut, [])
            if nouveau not in transitions:
                messages.error(
                    request,
                    f"Transition {panne.statut} → {nouveau} non autorisée.",
                )
            else:
                panne.commentaire_resolution = form.cleaned_data.get("commentaire", "")
                panne.statut = nouveau
                panne.save()
                fichiers = request.FILES.getlist("medias")
                _sauvegarder_medias_panne(fichiers, panne, request.user)
                messages.success(request, "Statut mis à jour.")
            return redirect("panne_detail", pk=panne.pk)
    return redirect("panne_detail", pk=panne.pk)


# ---------------------------------------------------------------------------
# Pannes – ajouter médias
# ---------------------------------------------------------------------------

@login_required
def panne_ajouter_media(request, pk):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)
    panne = get_object_or_404(Panne, pk=pk, site__in=sites)

    if profile.is_silo() and panne.declarant != request.user:
        raise PermissionDenied

    if request.method == "POST":
        fichiers = request.FILES.getlist("medias")
        if not fichiers:
            messages.error(request, "Aucun fichier sélectionné.")
        else:
            from .forms import valider_fichier
            erreurs = []
            valides = []
            for f in fichiers:
                try:
                    valider_fichier(f)
                    valides.append(f)
                except Exception as e:
                    erreurs.append(f"{f.name} : {e}")
            _sauvegarder_medias_panne(valides, panne, request.user)
            if erreurs:
                messages.warning(request, "Certains fichiers ont été rejetés : " + "; ".join(erreurs))
            if valides:
                messages.success(request, f"{len(valides)} fichier(s) ajouté(s).")
    return redirect("panne_detail", pk=panne.pk)


# ---------------------------------------------------------------------------
# Pannes – ajouter facture
# ---------------------------------------------------------------------------

@login_required
def panne_ajouter_facture(request, pk):
    profile = _get_profile(request)
    if not (profile.is_admin() or profile.is_maintenance()):
        raise PermissionDenied

    sites = _sites_autorises(request.user)
    panne = get_object_or_404(Panne, pk=pk, site__in=sites)

    if request.method == "POST":
        form = FactureForm(request.POST, request.FILES)
        if form.is_valid():
            facture = form.save(commit=False)
            facture.panne = panne
            fichier = form.cleaned_data.get("fichier_upload")
            if fichier:
                facture.fichier = fichier
                facture.nom_fichier_original = fichier.name
            facture.save()
            messages.success(request, "Facture ajoutée.")
        else:
            messages.error(request, "Erreur dans le formulaire de facture.")
    return redirect("panne_detail", pk=panne.pk)


# ---------------------------------------------------------------------------
# Maintenances préventives – liste
# ---------------------------------------------------------------------------

@login_required
def preventive_liste(request):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)

    if profile.is_silo():
        qs = MaintenancePreventive.objects.filter(destinataire=request.user)
    elif profile.is_maintenance():
        qs = MaintenancePreventive.objects.filter(site__in=sites, createur=request.user)
    else:  # admin
        qs = MaintenancePreventive.objects.filter(site__in=sites)

    qs = qs.select_related("site", "equipement", "createur", "destinataire").order_by("-creee_le")
    return render(
        request,
        "maintenance/preventive_liste.html",
        {"preventives": qs, "profile": profile},
    )


# ---------------------------------------------------------------------------
# Maintenances préventives – détail
# ---------------------------------------------------------------------------

@login_required
def preventive_detail(request, pk):
    profile = _get_profile(request)
    sites = _sites_autorises(request.user)
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)

    # Vérification des droits
    if profile.is_silo():
        if preventive.destinataire != request.user:
            raise PermissionDenied
    elif profile.is_maintenance():
        if preventive.createur != request.user and preventive.site not in sites:
            raise PermissionDenied
    else:  # admin
        if preventive.site not in sites:
            raise PermissionDenied

    medias = preventive.medias.all()
    terminer_form = None
    valider_form = None

    S = MaintenancePreventive.Statut
    if profile.is_silo() and preventive.statut in (S.RECUE, S.EN_COURS):
        terminer_form = PreventiveTerminerForm(instance=preventive)
    if profile.is_maintenance() and preventive.statut == S.A_VALIDER:
        valider_form = PreventiveValiderForm()

    ctx = {
        "preventive": preventive,
        "medias": medias,
        "profile": profile,
        "terminer_form": terminer_form,
        "valider_form": valider_form,
        "transitions": MaintenancePreventive.TRANSITIONS_AUTORISEES.get(preventive.statut, []),
    }
    return render(request, "maintenance/preventive_detail.html", ctx)


# ---------------------------------------------------------------------------
# Maintenances préventives – créer
# ---------------------------------------------------------------------------

@login_required
def preventive_creer(request):
    profile = _get_profile(request)
    if not (profile.is_admin() or profile.is_maintenance()):
        raise PermissionDenied

    if request.method == "POST":
        form = PreventiveCreerForm(request.POST, request.FILES, utilisateur=request.user)
        if form.is_valid():
            preventive = form.save(commit=False)
            preventive.createur = request.user
            preventive.statut = MaintenancePreventive.Statut.BROUILLON
            preventive.save()
            fichiers = request.FILES.getlist("medias")
            _sauvegarder_medias_preventive(fichiers, preventive, request.user)
            messages.success(request, "Tâche préventive créée (brouillon).")
            return redirect("preventive_detail", pk=preventive.pk)
    else:
        form = PreventiveCreerForm(utilisateur=request.user)
    return render(
        request,
        "maintenance/preventive_form.html",
        {"form": form, "profile": profile},
    )


# ---------------------------------------------------------------------------
# Maintenances préventives – envoyer
# ---------------------------------------------------------------------------

@login_required
def preventive_envoyer(request, pk):
    profile = _get_profile(request)
    if not (profile.is_admin() or profile.is_maintenance()):
        raise PermissionDenied

    sites = _sites_autorises(request.user)
    preventive = get_object_or_404(
        MaintenancePreventive,
        pk=pk,
        createur=request.user,
        statut__in=[MaintenancePreventive.Statut.BROUILLON, MaintenancePreventive.Statut.REJETEE],
    )
    if preventive.site not in sites:
        raise PermissionDenied

    preventive.statut = MaintenancePreventive.Statut.ENVOYEE
    preventive.save()
    messages.success(request, "Tâche envoyée à l'agent silo.")
    return redirect("preventive_detail", pk=preventive.pk)


# ---------------------------------------------------------------------------
# Maintenances préventives – recevoir (agent silo)
# ---------------------------------------------------------------------------

@login_required
def preventive_recevoir(request, pk):
    profile = _get_profile(request)
    if not profile.is_silo():
        raise PermissionDenied

    preventive = get_object_or_404(
        MaintenancePreventive,
        pk=pk,
        destinataire=request.user,
        statut=MaintenancePreventive.Statut.ENVOYEE,
    )
    preventive.statut = MaintenancePreventive.Statut.RECUE
    preventive.save()
    messages.success(request, "Tâche marquée comme reçue.")
    return redirect("preventive_detail", pk=preventive.pk)


# ---------------------------------------------------------------------------
# Maintenances préventives – démarrer (agent silo)
# ---------------------------------------------------------------------------

@login_required
def preventive_demarrer(request, pk):
    profile = _get_profile(request)
    if not profile.is_silo():
        raise PermissionDenied

    preventive = get_object_or_404(
        MaintenancePreventive,
        pk=pk,
        destinataire=request.user,
        statut=MaintenancePreventive.Statut.RECUE,
    )
    preventive.statut = MaintenancePreventive.Statut.EN_COURS
    preventive.save()
    messages.success(request, "Tâche démarrée.")
    return redirect("preventive_detail", pk=preventive.pk)


# ---------------------------------------------------------------------------
# Maintenances préventives – terminer (agent silo)
# ---------------------------------------------------------------------------

@login_required
def preventive_terminer(request, pk):
    profile = _get_profile(request)
    if not profile.is_silo():
        raise PermissionDenied

    preventive = get_object_or_404(
        MaintenancePreventive,
        pk=pk,
        destinataire=request.user,
        statut=MaintenancePreventive.Statut.EN_COURS,
    )
    if request.method == "POST":
        form = PreventiveTerminerForm(request.POST, request.FILES, instance=preventive)
        if form.is_valid():
            preventive = form.save(commit=False)
            preventive.statut = MaintenancePreventive.Statut.A_VALIDER
            preventive.save()
            fichiers = request.FILES.getlist("medias")
            _sauvegarder_medias_preventive(fichiers, preventive, request.user)
            messages.success(request, "Tâche terminée. En attente de validation.")
            return redirect("preventive_detail", pk=preventive.pk)
    else:
        form = PreventiveTerminerForm(instance=preventive)
    return render(
        request,
        "maintenance/preventive_terminer.html",
        {"form": form, "preventive": preventive, "profile": profile},
    )


# ---------------------------------------------------------------------------
# Maintenances préventives – valider/rejeter (agent maintenance)
# ---------------------------------------------------------------------------

@login_required
def preventive_valider(request, pk):
    profile = _get_profile(request)
    if not (profile.is_admin() or profile.is_maintenance()):
        raise PermissionDenied

    sites = _sites_autorises(request.user)
    preventive = get_object_or_404(
        MaintenancePreventive,
        pk=pk,
        statut=MaintenancePreventive.Statut.A_VALIDER,
    )
    if preventive.site not in sites:
        raise PermissionDenied
    # L'agent maintenance ne peut valider que ses propres tâches
    if profile.is_maintenance() and preventive.createur != request.user:
        raise PermissionDenied

    if request.method == "POST":
        form = PreventiveValiderForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data["decision"]
            commentaire = form.cleaned_data.get("commentaire", "")
            preventive.commentaire_validation = commentaire
            if decision == "valider":
                preventive.statut = MaintenancePreventive.Statut.VALIDEE
                messages.success(request, "Tâche validée.")
            else:
                preventive.statut = MaintenancePreventive.Statut.REJETEE
                messages.warning(request, "Tâche rejetée.")
            preventive.save()
            return redirect("preventive_detail", pk=preventive.pk)
    else:
        form = PreventiveValiderForm()
    return render(
        request,
        "maintenance/preventive_valider.html",
        {"form": form, "preventive": preventive, "profile": profile},
    )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@login_required
def notification_liste(request):
    notifications = Notification.objects.filter(utilisateur=request.user)
    non_lues = notifications.filter(lue=False).count()
    return render(
        request,
        "maintenance/notification_liste.html",
        {"notifications": notifications[:50], "non_lues": non_lues},
    )


@login_required
def notification_marquer_lue(request, pk):
    notif = get_object_or_404(Notification, pk=pk, utilisateur=request.user)
    notif.lue = True
    notif.save()
    return redirect(notif.lien or "notification_liste")


@login_required
def notification_tout_lire(request):
    Notification.objects.filter(utilisateur=request.user, lue=False).update(lue=True)
    messages.success(request, "Toutes les notifications marquées comme lues.")
    return redirect("notification_liste")
