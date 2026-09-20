from datetime import date, timedelta
import csv
from decimal import Decimal
import json
from importlib import import_module
from io import BytesIO
from typing import cast
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.timezone import localdate
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
    TemplateView,
    View,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
import qrcode
from vehicules.models import Vehicule

from .forms import (
    CelluleGrainForm,
    CelluleSiloFormSet,
    CelluleSiteLegacyFormSet,
    EquipementForm,
    MouvementPieceForm,
    PieceDetacheeForm,
    FactureForm,
    FacturePdfUploadForm,
    MaintenancePreventiveForm,
    PanneAffectationForm,
    PanneFactureUploadForm,
    PanneForm,
    PanneMediaForm,
    PannePrioriteForm,
    PanneStatutForm,
    PanneTempsInterventionForm,
    PreventiveStatutForm,
    PreventiveTerminerForm,
    PreventiveValiderForm,
    ProfileUpdateForm,
    ReleveCelluleForm,
    ReleveStockageAPlatForm,
    SiteForm,
    SiloSiteFormSet,
    StockageAPlatForm,
    TypeGrainForm,
    UtilisateurCreateForm,
    UtilisateurUpdateForm,
)
from .mixins import (
    AdminRequiredMixin,
    AdminSiloMaintenanceRequiredMixin,
    AdminSiloRequiredMixin,
    MaintenanceRequiredMixin,
    SiloRequiredMixin,
    get_sites_utilisateur,
)
from .models import (
    CelluleGrain,
    Equipement,
    MouvementPiece,
    PieceDetachee,
    Facture,
    HistoriquePanne,
    HistoriquePreventive,
    MaintenancePreventive,
    Notification,
    Panne,
    PanneMedia,
    PanneTempsIntervention,
    PreventiveMedia,
    Profile,
    ReleveCellule,
    ReleveStockageAPlat,
    Silo,
    Site,
    SitePhoto,
    StockageAPlat,
    TypeGrain,
)
from .signals import (
    notifier_admin_preventive_en_attente,
    notifier_affectation_panne,
    supprimer_notifications_declaration_panne,
)

try:
    extract_invoice_data_from_document = import_module(
        '.facture_extraction', package=__package__
    ).extract_invoice_data_from_document
except ModuleNotFoundError:  # module optionnel absent localement
    extract_invoice_data_from_document = None

# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

STATUTS_PANNE_ACTIFS = [
    Panne.STATUT_AFFECTEE,
    Panne.STATUT_EN_COURS,
    Panne.STATUT_ATTENTE_PIECES,
    Panne.STATUT_IMPREVUS,
]


def _pannes_actives_affectees(user):
    return Panne.objects.filter(
        affecte_a=user,
        statut__in=STATUTS_PANNE_ACTIFS,
    )


def _maintenance_peut_valider_preventive(user, preventive):
    if not preventive.equipement_id:
        return False
    return _pannes_actives_affectees(user).filter(
        equipement_id=preventive.equipement_id
    ).exists()


def _ajouter_stock_resume(resumes, cle, libelle, cellule, dernier_releve):
    resume = resumes.setdefault(cle, {
        'id': cle,
        'libelle': libelle,
        'stock': Decimal('0'),
        'stock_cellules': Decimal('0'),
        'stock_a_plat': Decimal('0'),
        'capacite': Decimal('0'),
        'cellules': 0,
        'cellules_relevees': 0,
    })
    resume['capacite'] += cellule.capacite_tonnes
    resume['cellules'] += 1
    if dernier_releve:
        resume['stock'] += dernier_releve.masse_estimee_tonnes
        resume['stock_cellules'] += dernier_releve.masse_estimee_tonnes
        resume['cellules_relevees'] += 1


def _ajouter_stock_a_plat_resume(resumes, cle, libelle, tonnage):
    resume = resumes.setdefault(cle, {
        'id': cle,
        'libelle': libelle,
        'stock': Decimal('0'),
        'stock_cellules': Decimal('0'),
        'stock_a_plat': Decimal('0'),
        'capacite': Decimal('0'),
        'cellules': 0,
        'cellules_relevees': 0,
    })
    resume['stock'] += tonnage
    resume['stock_a_plat'] += tonnage


def _finaliser_resumes_stock(resumes, nom_libelle):
    resultats = []
    for resume in resumes.values():
        resume[nom_libelle] = resume.pop('libelle')
        resume['taux'] = (
            resume['stock_cellules'] / resume['capacite'] * Decimal('100')
            if resume['capacite']
            else Decimal('0')
        )
        resultats.append(resume)
    return sorted(resultats, key=lambda resume: resume[nom_libelle].lower())


@login_required
def dashboard(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    sites = get_sites_utilisateur(user)
    ctx = {'profile': profile, 'sites': sites}

    if profile.is_admin():
        pannes = Panne.objects.filter(site__in=sites)
        preventives = MaintenancePreventive.objects.filter(
            Q(site__in=sites) | Q(equipement__site__in=sites))
        factures = Facture.objects.filter(panne__site__in=sites)
        analytics_site = request.GET.get('analytics_site', '').strip()
        analytics_equipment = request.GET.get(
            'analytics_equipment', '').strip()
        analytics_start = request.GET.get('analytics_start', '').strip()
        analytics_end = request.GET.get('analytics_end', '').strip()
        try:
            analytics_start_date = date.fromisoformat(
                analytics_start) if analytics_start else None
        except ValueError:
            analytics_start_date = None
        try:
            analytics_end_date = date.fromisoformat(
                analytics_end) if analytics_end else None
        except ValueError:
            analytics_end_date = None
        if analytics_start_date and analytics_end_date and analytics_start_date > analytics_end_date:
            analytics_start_date, analytics_end_date = analytics_end_date, analytics_start_date
        if analytics_site:
            pannes = pannes.filter(site_id=analytics_site)
            preventives = preventives.filter(
                Q(site_id=analytics_site) | Q(equipement__site_id=analytics_site))
            factures = factures.filter(panne__site_id=analytics_site)
        if analytics_equipment:
            pannes = pannes.filter(equipement_id=analytics_equipment)
            preventives = preventives.filter(equipement_id=analytics_equipment)
            factures = factures.filter(
                panne__equipement_id=analytics_equipment)
        if analytics_start_date:
            pannes = pannes.filter(
                date_signalement__date__gte=analytics_start_date)
            preventives = preventives.filter(
                date_echeance__date__gte=analytics_start_date)
            factures = factures.filter(date_facture__gte=analytics_start_date)
        if analytics_end_date:
            pannes = pannes.filter(
                date_signalement__date__lte=analytics_end_date)
            preventives = preventives.filter(
                date_echeance__date__lte=analytics_end_date)
            factures = factures.filter(date_facture__lte=analytics_end_date)
        analytics_equipment_queryset = Equipement.objects.filter(
            site__in=sites, actif=True).order_by('nom')
        cellules = CelluleGrain.objects.filter(
            site__in=sites,
            actif=True,
        ).select_related('site', 'type_grain').prefetch_related(Prefetch(
            'releves',
            queryset=ReleveCellule.objects.order_by('-releve_le', '-pk'),
            to_attr='derniers_releves_prefetches',
        ))
        stocks_grains = {}
        stocks_sites = {}
        stocks_grains_par_site = {}
        stocks_sites_par_grain = {}
        stock_total_tonnes = Decimal('0')
        capacite_totale_tonnes = Decimal('0')
        cellules_sans_releve = 0
        cellules_vides = 0
        cellules_maintenance = 0
        for cellule in cellules:
            if cellule.etat == CelluleGrain.Etat.VIDE:
                cellules_vides += 1
                continue
            if cellule.etat in {
                CelluleGrain.Etat.REPARATION,
                CelluleGrain.Etat.NETTOYAGE,
            }:
                cellules_maintenance += 1
                continue
            dernier_releve = cellule.dernier_releve
            if not cellule.type_grain_id:
                continue
            grain_id = cellule.type_grain_id
            grain_nom = cellule.type_grain.nom
            _ajouter_stock_resume(
                stocks_grains, grain_id, grain_nom, cellule, dernier_releve
            )
            _ajouter_stock_resume(
                stocks_sites, cellule.site_id, cellule.site.nom, cellule, dernier_releve
            )
            _ajouter_stock_resume(
                stocks_grains_par_site.setdefault(cellule.site_id, {}),
                grain_id,
                grain_nom,
                cellule,
                dernier_releve,
            )
            _ajouter_stock_resume(
                stocks_sites_par_grain.setdefault(grain_id, {}),
                cellule.site_id,
                cellule.site.nom,
                cellule,
                dernier_releve,
            )
            capacite_totale_tonnes += cellule.capacite_tonnes
            if dernier_releve:
                stock_total_tonnes += dernier_releve.masse_estimee_tonnes
            else:
                cellules_sans_releve += 1

        stock_cellules_tonnes = stock_total_tonnes
        stockages_a_plat = StockageAPlat.objects.filter(
            site__in=sites,
            actif=True,
        ).select_related('site', 'type_grain').prefetch_related(Prefetch(
            'releves',
            queryset=ReleveStockageAPlat.objects.select_related(
                'type_grain'
            ).order_by('-releve_le', '-pk'),
            to_attr='releves_prefetches',
        ))
        for stockage in stockages_a_plat:
            for dernier_releve in stockage.derniers_releves_par_grain:
                tonnage = dernier_releve.tonnage
                grain_id = dernier_releve.type_grain_id
                grain_nom = dernier_releve.type_grain.nom
                _ajouter_stock_a_plat_resume(
                    stocks_grains, grain_id, grain_nom, tonnage
                )
                _ajouter_stock_a_plat_resume(
                    stocks_sites, stockage.site_id, stockage.site.nom, tonnage
                )
                _ajouter_stock_a_plat_resume(
                    stocks_grains_par_site.setdefault(stockage.site_id, {}),
                    grain_id,
                    grain_nom,
                    tonnage,
                )
                _ajouter_stock_a_plat_resume(
                    stocks_sites_par_grain.setdefault(grain_id, {}),
                    stockage.site_id,
                    stockage.site.nom,
                    tonnage,
                )
                stock_total_tonnes += tonnage

        vehicules = list(Vehicule.objects.filter(
            site__in=sites,
            categorie__in=[
                Vehicule.Categorie.POIDS_LOURD,
                Vehicule.Categorie.ENGIN_MANUTENTION,
                Vehicule.Categorie.REMORQUE_POIDS_LOURD,
            ],
        ).exclude(
            statut=Vehicule.Statut.CEDE
        ).select_related('site'))
        vehicules_alertes = [
            vehicule for vehicule in vehicules if vehicule.alerte_echeance
        ]
        vehicules_indisponibles = sum(
            vehicule.statut in {
                Vehicule.Statut.EN_ENTRETIEN,
                Vehicule.Statut.HORS_SERVICE,
            }
            for vehicule in vehicules
        )
        pannes_nouvelles = pannes.filter(
            affecte_a__isnull=True,
            statut=Panne.STATUT_NOUVELLE,
        )
        stocks_par_site = _finaliser_resumes_stock(stocks_sites, 'site')
        stocks_par_grain = _finaliser_resumes_stock(stocks_grains, 'grain')
        for resume_grain in stocks_par_grain:
            resume_grain['sites'] = _finaliser_resumes_stock(
                stocks_sites_par_grain.get(resume_grain['id'], {}),
                'site',
            )
        sites_par_id = {site.pk: site for site in sites}
        for resume_site in stocks_par_site:
            site = sites_par_id[resume_site['id']]
            resume_site['grains'] = _finaliser_resumes_stock(
                stocks_grains_par_site.get(site.pk, {}),
                'grain',
            )
            vehicules_site = [
                vehicule for vehicule in vehicules
                if vehicule.site_id == site.pk
            ]
            resume_site['pannes_ouvertes'] = pannes.filter(
                site=site,
            ).exclude(
                statut__in=[Panne.STATUT_ARCHIVEE, Panne.STATUT_ANNULEE]
            ).count()
            resume_site['vehicules_total'] = len(vehicules_site)
            resume_site['vehicules_disponibles'] = sum(
                vehicule.statut in {
                    Vehicule.Statut.DISPONIBLE,
                    Vehicule.Statut.EN_SERVICE,
                }
                for vehicule in vehicules_site
            )
        analytics_labels = []
        analytics_pannes = []
        analytics_factures = []
        month_names = (
            "Jan", "Fév", "Mar", "Avr", "Mai", "Juin",
            "Juil", "Août", "Sep", "Oct", "Nov", "Déc",
        )
        current_month = localdate().replace(day=1)
        for offset in range(5, -1, -1):
            month_index = current_month.month - 1 - offset
            year = current_month.year + month_index // 12
            month = month_index % 12 + 1
            month_start = date(year, month, 1)
            next_month = date(
                year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            analytics_labels.append(f"{month_names[month - 1]} {year}")
            analytics_pannes.append(pannes.filter(
                date_signalement__date__gte=month_start,
                date_signalement__date__lt=next_month,
            ).count())
            analytics_factures.append(float(factures.filter(
                date_facture__gte=month_start,
                date_facture__lt=next_month,
            ).aggregate(total=Sum("montant_ttc"))["total"] or 0))
        interventions_count = PanneTempsIntervention.objects.filter(
            panne__in=pannes,
            validee=True,
        ).count()
        preventive_terminees = preventives.filter(
            statut__in=[
                MaintenancePreventive.Statut.EFFECTUEE,
                MaintenancePreventive.Statut.VALIDEE,
            ],
            date_echeance__lte=timezone.now(),
        ).count()
        preventive_echues = preventives.filter(
            date_echeance__lte=timezone.now(),
        ).exclude(
            statut__in=[MaintenancePreventive.Statut.BROUILLON,
                        MaintenancePreventive.Statut.ANNULEE,
                        MaintenancePreventive.Statut.ARCHIVEE],
        ).count()
        interventions = PanneTempsIntervention.objects.filter(
            panne__in=pannes,
            validee=True,
        )
        temps_intervention = interventions.aggregate(
            total=Sum('duree_minutes'), cout=Sum('montant'))
        analytics_sites = sites.filter(
            pk=analytics_site) if analytics_site else sites
        equipment_queryset = Equipement.objects.filter(
            site__in=analytics_sites,
            actif=True,
        )
        if analytics_equipment:
            equipment_queryset = equipment_queryset.filter(
                pk=analytics_equipment)
        site_costs = []
        for site in analytics_sites:
            invoice_cost = factures.filter(panne__site=site).aggregate(
                total=Sum('montant_ttc'))['total'] or Decimal('0')
            intervention_cost = interventions.filter(
                panne__site=site,
            ).aggregate(total=Sum('montant'))['total'] or Decimal('0')
            site_costs.append({
                'label': site.nom,
                'cost': float(invoice_cost + intervention_cost),
            })
        equipment_gaps = []
        for equipment in equipment_queryset.prefetch_related('pannes'):
            resolved_queryset = equipment.pannes.filter(
                statut__in=[Panne.Statut.RESOLUE, Panne.Statut.CLOTUREE],
                date_resolution__isnull=False,
            )
            if analytics_start_date:
                resolved_queryset = resolved_queryset.filter(
                    date_resolution__date__gte=analytics_start_date)
            if analytics_end_date:
                resolved_queryset = resolved_queryset.filter(
                    date_resolution__date__lte=analytics_end_date)
            resolved_dates = list(resolved_queryset.values_list(
                'date_resolution', flat=True).order_by('date_resolution'))
            if len(resolved_dates) >= 2:
                gaps = [
                    (later - earlier).days
                    for earlier, later in zip(resolved_dates, resolved_dates[1:])
                ]
                equipment_gaps.append({
                    'label': equipment.nom,
                    'days': round(sum(gaps) / len(gaps), 1),
                })
        equipment_gaps.sort(key=lambda item: item['days'])
        ctx.update({
            'pannes_ouvertes': pannes.exclude(
                statut__in=[Panne.STATUT_ARCHIVEE, Panne.STATUT_ANNULEE]
            ).count(),
            'pannes_non_assignees': pannes.filter(
                affecte_a__isnull=True,
                statut=Panne.STATUT_NOUVELLE,
            ).exists(),
            'pannes_a_affecter': pannes_nouvelles.count(),
            'pannes_critiques': pannes_nouvelles.filter(
                priorite=Panne.PRIORITE_CRITIQUE,
            ).count(),
            'pannes_en_traitement': pannes.filter(
                statut__in=STATUTS_PANNE_ACTIFS,
            ).count(),
            'preventives_retard': preventives.filter(date_echeance__date__lt=localdate(), statut=MaintenancePreventive.Statut.EN_RETARD).count(),
            'factures_non_validees': factures.filter(validee=False).count(),
            'pannes_a_affecter_recentes': pannes_nouvelles.select_related(
                'site', 'equipement', 'signale_par', 'affecte_a'
            ).order_by('-date_signalement')[:5],
            'pannes_recentes': pannes.exclude(
                statut=Panne.STATUT_ARCHIVEE,
            ).select_related(
                'site', 'equipement', 'signale_par', 'affecte_a'
            ).order_by('-date_signalement')[:5],
            'preventives_recentes': preventives.select_related(
                'site', 'equipement', 'affecte_a'
            ).order_by('-updated_at')[:5],
            'stocks_par_grain': stocks_par_grain,
            'stocks_par_site': stocks_par_site,
            'stock_total_tonnes': stock_total_tonnes,
            'capacite_totale_tonnes': capacite_totale_tonnes,
            'taux_stock_global': (
                stock_cellules_tonnes
                / capacite_totale_tonnes
                * Decimal('100')
                if capacite_totale_tonnes
                else Decimal('0')
            ),
            'cellules_sans_releve': cellules_sans_releve,
            'cellules_vides': cellules_vides,
            'cellules_maintenance': cellules_maintenance,
            'vehicules_actifs': len(vehicules),
            'vehicules_indisponibles': vehicules_indisponibles,
            'vehicules_disponibles': sum(
                vehicule.statut in {
                    Vehicule.Statut.DISPONIBLE,
                    Vehicule.Statut.EN_SERVICE,
                }
                for vehicule in vehicules
            ),
            'vehicules_entretien': sum(
                vehicule.statut == Vehicule.Statut.EN_ENTRETIEN
                for vehicule in vehicules
            ),
            'vehicules_hors_service': sum(
                vehicule.statut == Vehicule.Statut.HORS_SERVICE
                for vehicule in vehicules
            ),
            'vehicules_alertes': vehicules_alertes[:5],
            'vehicules_alertes_count': len(vehicules_alertes),
            'dashboard_analytics': json.dumps({
                'labels': analytics_labels,
                'pannes': analytics_pannes,
                'factures': analytics_factures,
            }),
            'maintenance_metrics': {
                'mttr_minutes': round((temps_intervention['total'] or 0) / interventions_count) if interventions_count else 0,
                'cout_interventions': float(temps_intervention['cout'] or 0),
                'interventions': interventions_count,
                'preventive_rate': round(
                    preventive_terminees * 100 / preventive_echues
                ) if preventive_echues else 100,
            },
            'analytics_filters': {
                'site': analytics_site,
                'equipment': analytics_equipment,
                'start': analytics_start_date.isoformat() if analytics_start_date else '',
                'end': analytics_end_date.isoformat() if analytics_end_date else '',
            },
            'analytics_equipment': analytics_equipment_queryset,
            'dashboard_analytics_extended': json.dumps({
                'site_costs': site_costs,
                'equipment_mtbf': equipment_gaps[:8],
                'preventive_rate': round(
                    preventive_terminees * 100 / preventive_echues
                ) if preventive_echues else 100,
            }),
        })

    elif profile.is_maintenance():
        pannes = Panne.objects.filter(affecte_a=user).exclude(
            statut=Panne.STATUT_ARCHIVEE)
        pannes_actives = _pannes_actives_affectees(user)
        preventives_liees = MaintenancePreventive.objects.filter(
            equipement_id__in=pannes_actives.exclude(
                equipement__isnull=True
            ).values('equipement_id')
        )
        ctx.update({
            'pannes_affectees': pannes_actives.count(),
            'pannes_a_affecter': 0,
            'pannes_recentes': pannes.order_by('-updated_at')[:5],
            'preventives_recentes': preventives_liees.select_related(
                'site', 'equipement', 'affecte_a'
            ).order_by('-updated_at')[:5],
        })

    else:  # silo
        pannes = Panne.objects.filter(
            signale_par=user
        ).exclude(statut=Panne.STATUT_ARCHIVEE)
        ctx.update({
            'pannes_declarees': pannes.count(),
            'taches_recues': MaintenancePreventive.objects.filter(
                (Q(site__in=sites) | Q(equipement__site__in=sites)),
                affecte_a=user,
                statut__in=[MaintenancePreventive.Statut.ENVOYEE,
                            MaintenancePreventive.Statut.RECUE],
            ).count(),
            'pannes_recentes': pannes.order_by('-created_at')[:5],
            'preventives_recentes': MaintenancePreventive.objects.filter(
                (Q(site__in=sites) | Q(equipement__site__in=sites)),
                affecte_a=user,
            ).exclude(
                statut=MaintenancePreventive.Statut.ARCHIVEE,
            ).order_by('-updated_at')[:5],
        })

    return render(request, 'maintenance/dashboard.html', ctx)


# ─────────────────────────────────────────────
# SITES
# ─────────────────────────────────────────────

class SiteListView(AdminRequiredMixin, ListView):
    model = Site
    template_name = 'maintenance/site_list.html'
    context_object_name = 'sites'

    def get_queryset(self):
        return Site.objects.annotate(
            nombre_silos=Count('silos', distinct=True),
            nombre_cellules=Count('silos__cellules', distinct=True),
        ).prefetch_related('photos')


def _ajouter_photos_site(site, photos, utilisateur):
    for photo in photos:
        SitePhoto.objects.create(
            site=site,
            fichier=photo,
            nom_original=photo.name,
            ajoutee_par=utilisateur,
        )


def _construire_formsets_silos(request, site, silo_formset=None):
    donnees = request.POST if 'silos-TOTAL_FORMS' in request.POST else None
    silo_formset = silo_formset or SiloSiteFormSet(
        donnees,
        instance=site,
        prefix='silos',
    )
    for index, silo_form in enumerate(silo_formset.forms):
        silo = silo_form.instance
        if not silo.site_id:
            silo.site = site
        prefix = f'silos-{index}-cellules'
        donnees_cellules = request.POST if f'{prefix}-TOTAL_FORMS' in request.POST else None
        silo_form.cellule_formset = CelluleSiloFormSet(
            donnees_cellules,
            instance=silo,
            prefix=prefix,
        )
    return silo_formset


def _formsets_silos_valides(silo_formset):
    silos_valides = silo_formset.is_valid()
    if not silos_valides:
        return False
    cellules_valides = True
    for silo_form in silo_formset.forms:
        if silo_form.cleaned_data.get('DELETE'):
            continue
        cellule_formset = silo_form.cellule_formset
        cellules_modifiees = any(form.has_changed()
                                 for form in cellule_formset.forms)
        silo_present = bool(silo_form.instance.pk or silo_form.has_changed())
        if cellules_modifiees and not silo_form.cleaned_data.get('nom'):
            silo_form.add_error(
                'nom', 'Nommez le silo avant d’ajouter ses cellules.')
            cellules_valides = False
        if silo_present or cellules_modifiees:
            cellules_valides = cellule_formset.is_valid() and cellules_valides
    return silos_valides and cellules_valides


def _construire_structure_site(request, site):
    if 'silos-TOTAL_FORMS' in request.POST:
        silo_formset = _construire_formsets_silos(request, site)
        return silo_formset, None
    if 'cellules-TOTAL_FORMS' in request.POST:
        cellule_formset = CelluleSiteLegacyFormSet(
            request.POST,
            instance=site,
            prefix='cellules',
        )
        return None, cellule_formset
    return None, None


def _enregistrer_formsets_silos(silo_formset, site):
    for silo_form in silo_formset.forms:
        if silo_form.cleaned_data.get('DELETE'):
            if silo_form.instance.pk:
                silo_form.instance.delete()
            continue
        cellule_formset = silo_form.cellule_formset
        cellules_modifiees = any(form.has_changed()
                                 for form in cellule_formset.forms)
        if not silo_form.instance.pk and not silo_form.has_changed() and not cellules_modifiees:
            continue
        silo = silo_form.save(commit=False)
        silo.site = site
        silo.save()
        cellule_formset.instance = silo
        cellule_formset.save()


class SiteCreateView(AdminRequiredMixin, CreateView):
    model = Site
    form_class = SiteForm
    template_name = 'maintenance/site_form.html'
    success_url = reverse_lazy('site_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['silo_formset'] = _construire_formsets_silos(
            self.request,
            self.object or Site(),
            kwargs.get('silo_formset'),
        )
        return context

    def form_valid(self, form):
        silo_formset, cellule_formset = _construire_structure_site(
            self.request, form.instance
        )
        structure_valide = (
            _formsets_silos_valides(silo_formset)
            if silo_formset is not None
            else cellule_formset is None or cellule_formset.is_valid()
        )
        if not structure_valide:
            return self.render_to_response(self.get_context_data(
                form=form,
                silo_formset=silo_formset,
            ))
        with transaction.atomic():
            response = super().form_valid(form)
            if silo_formset is not None:
                _enregistrer_formsets_silos(silo_formset, self.object)
            elif cellule_formset is not None:
                cellule_formset.instance = self.object
                cellule_formset.save()
            _ajouter_photos_site(
                self.object,
                form.cleaned_data.get('photos', []),
                self.request.user,
            )
        messages.success(self.request, 'Site créé avec succès.')
        return response


class SiteUpdateView(AdminRequiredMixin, UpdateView):
    model = Site
    form_class = SiteForm
    template_name = 'maintenance/site_form.html'
    success_url = reverse_lazy('site_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['silo_formset'] = _construire_formsets_silos(
            self.request,
            self.object,
            kwargs.get('silo_formset'),
        )
        return context

    def form_valid(self, form):
        silo_formset, cellule_formset = _construire_structure_site(
            self.request, form.instance
        )
        structure_valide = (
            _formsets_silos_valides(silo_formset)
            if silo_formset is not None
            else cellule_formset is None or cellule_formset.is_valid()
        )
        if not structure_valide:
            return self.render_to_response(self.get_context_data(
                form=form,
                silo_formset=silo_formset,
            ))
        with transaction.atomic():
            response = super().form_valid(form)
            if silo_formset is not None:
                _enregistrer_formsets_silos(silo_formset, self.object)
            elif cellule_formset is not None:
                cellule_formset.save()
            _ajouter_photos_site(
                self.object,
                form.cleaned_data.get('photos', []),
                self.request.user,
            )
        messages.success(self.request, 'Site mis à jour.')
        return response


class SiteDeleteView(AdminRequiredMixin, DeleteView):
    model = Site
    template_name = 'maintenance/confirm_delete.html'
    success_url = reverse_lazy('site_list')

    def form_valid(self, form):
        fichiers_photos = [
            photo.fichier
            for photo in self.object.photos.all()
            if photo.fichier
        ]
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                "Ce site ne peut pas être supprimé car il est lié à des "
                "équipements ou à un historique de maintenance.",
            )
            return redirect(self.success_url)
        for fichier in fichiers_photos:
            fichier.delete(save=False)
        messages.success(self.request, 'Site supprimé.')
        return response


class SitePhotoDeleteView(AdminRequiredMixin, DeleteView):
    model = SitePhoto
    template_name = 'maintenance/confirm_delete.html'

    def get_success_url(self):
        return reverse('site_update', kwargs={'pk': self.object.site_id})

    def form_valid(self, form):
        if self.object.fichier:
            self.object.fichier.delete(save=False)
        messages.success(self.request, 'Photo supprimée.')
        return super().form_valid(form)


@login_required
def site_photo_afficher(request, pk):
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied
    photo = get_object_or_404(SitePhoto, pk=pk)
    return FileResponse(
        photo.fichier.open('rb'),
        as_attachment=False,
        filename=photo.nom_telechargement,
    )


# ─────────────────────────────────────────────
# GESTION DES SILOS
# ─────────────────────────────────────────────

class GestionSilosView(AdminSiloRequiredMixin, ListView):
    model = CelluleGrain
    template_name = 'maintenance/gestion_silos.html'
    context_object_name = 'cellules'

    def get_queryset(self):
        queryset = CelluleGrain.objects.filter(
            site__in=get_sites_utilisateur(self.request.user)
        ).select_related('site', 'silo', 'type_grain').prefetch_related(
            Prefetch(
                'releves',
                queryset=ReleveCellule.objects.select_related(
                    'type_grain', 'releve_par'
                ).order_by('-releve_le', '-pk')[:1],
                to_attr='derniers_releves_prefetches',
            ),
        )
        site_id = self.request.GET.get('site')
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        type_grain_id = self.request.GET.get('type_grain')
        if type_grain_id:
            queryset = queryset.filter(type_grain_id=type_grain_id)
        if not self.request.user.profile.is_admin():
            queryset = queryset.filter(actif=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sites'] = get_sites_utilisateur(self.request.user)
        context['filtres_types_grain'] = TypeGrain.objects.filter(actif=True)
        stockages_a_plat = StockageAPlat.objects.filter(
            site__in=context['sites']
        ).select_related('site', 'type_grain').prefetch_related(Prefetch(
            'releves',
            queryset=ReleveStockageAPlat.objects.select_related(
                'releve_par', 'type_grain'
            ).order_by('-releve_le', '-pk'),
            to_attr='releves_prefetches',
        ))
        site_id = self.request.GET.get('site')
        if site_id:
            stockages_a_plat = stockages_a_plat.filter(site_id=site_id)
        type_grain_id = self.request.GET.get('type_grain')
        if type_grain_id:
            stockages_a_plat = stockages_a_plat.filter(
                releves__type_grain_id=type_grain_id
            ).distinct()
        if not self.request.user.profile.is_admin():
            stockages_a_plat = stockages_a_plat.filter(actif=True)
        context['stockages_a_plat'] = stockages_a_plat
        if self.request.user.profile.is_admin():
            context['types_grain'] = TypeGrain.objects.all()
        return context


class StockageAPlatCreateView(SiloRequiredMixin, CreateView):
    model = StockageAPlat
    form_class = StockageAPlatForm
    template_name = 'maintenance/stockage_a_plat_form.html'
    success_url = reverse_lazy('gestion_silos')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['sites'] = get_sites_utilisateur(self.request.user)
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Stockage à plat créé avec succès.')
        return super().form_valid(form)


class StockageAPlatUpdateView(AdminRequiredMixin, UpdateView):
    model = StockageAPlat
    form_class = StockageAPlatForm
    template_name = 'maintenance/stockage_a_plat_form.html'
    success_url = reverse_lazy('gestion_silos')

    def form_valid(self, form):
        messages.success(self.request, 'Stockage à plat mis à jour.')
        return super().form_valid(form)


class StockageAPlatDetailView(AdminSiloRequiredMixin, DetailView):
    model = StockageAPlat
    template_name = 'maintenance/stockage_a_plat_detail.html'
    context_object_name = 'stockage'

    def get_queryset(self):
        return StockageAPlat.objects.filter(
            site__in=get_sites_utilisateur(self.request.user)
        ).select_related('site', 'type_grain').prefetch_related(
            'releves__releve_par'
        )


@login_required
def stockage_a_plat_relever(request, pk):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.is_silo():
        raise PermissionDenied
    stockage = get_object_or_404(
        StockageAPlat.objects.filter(
            site__in=get_sites_utilisateur(request.user),
            actif=True,
        ).select_related('site', 'type_grain'),
        pk=pk,
    )
    initial = {'releve_le': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}
    initial['type_grain'] = stockage.type_grain_id
    form = ReleveStockageAPlatForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        releve = form.save(commit=False)
        releve.stockage = stockage
        releve.releve_par = request.user
        releve.save()
        messages.success(request, 'Tonnage du stockage à plat enregistré.')
        return redirect('stockage_a_plat_detail', pk=stockage.pk)
    return render(request, 'maintenance/releve_stockage_a_plat_form.html', {
        'form': form,
        'stockage': stockage,
    })


class CelluleGrainCreateView(AdminRequiredMixin, CreateView):
    model = CelluleGrain
    form_class = CelluleGrainForm
    template_name = 'maintenance/cellule_grain_form.html'
    success_url = reverse_lazy('gestion_silos')

    def form_valid(self, form):
        messages.success(self.request, 'Cellule créée avec succès.')
        return super().form_valid(form)


class CelluleGrainUpdateView(AdminRequiredMixin, UpdateView):
    model = CelluleGrain
    form_class = CelluleGrainForm
    template_name = 'maintenance/cellule_grain_form.html'
    success_url = reverse_lazy('gestion_silos')

    def form_valid(self, form):
        messages.success(self.request, 'Cellule mise à jour.')
        return super().form_valid(form)


class TypeGrainCreateView(AdminRequiredMixin, CreateView):
    model = TypeGrain
    form_class = TypeGrainForm
    template_name = 'maintenance/type_grain_form.html'
    success_url = reverse_lazy('gestion_silos')

    def form_valid(self, form):
        messages.success(self.request, 'Type de grain ajouté.')
        return super().form_valid(form)


class TypeGrainUpdateView(AdminRequiredMixin, UpdateView):
    model = TypeGrain
    form_class = TypeGrainForm
    template_name = 'maintenance/type_grain_form.html'
    success_url = reverse_lazy('gestion_silos')

    def form_valid(self, form):
        messages.success(self.request, 'Type de grain mis à jour.')
        return super().form_valid(form)


class CelluleGrainDetailView(AdminSiloRequiredMixin, DetailView):
    model = CelluleGrain
    template_name = 'maintenance/cellule_grain_detail.html'
    context_object_name = 'cellule'

    def get_queryset(self):
        return CelluleGrain.objects.filter(
            site__in=get_sites_utilisateur(self.request.user)
        ).select_related('site', 'silo', 'type_grain').prefetch_related(
            'releves__type_grain',
            'releves__releve_par',
        )


@login_required
def cellule_grain_relever(request, pk):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.is_silo():
        raise PermissionDenied
    cellule = get_object_or_404(
        CelluleGrain.objects.filter(
            site__in=get_sites_utilisateur(request.user),
            actif=True,
        ).select_related('site', 'type_grain'),
        pk=pk,
    )
    if cellule.etat != CelluleGrain.Etat.EN_SERVICE:
        messages.error(
            request,
            f"Cette cellule est actuellement {cellule.get_etat_display().lower()}.",
        )
        return redirect('cellule_grain_detail', pk=cellule.pk)
    if not cellule.type_grain_id:
        messages.error(
            request,
            "Le type de grain doit être configuré sur la cellule avant la saisie du stock.",
        )
        return redirect('cellule_grain_detail', pk=cellule.pk)
    initial = {'releve_le': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}
    form = ReleveCelluleForm(
        request.POST or None,
        cellule=cellule,
        initial=initial,
    )
    if request.method == 'POST' and form.is_valid():
        releve = form.save(commit=False)
        releve.cellule = cellule
        releve.releve_par = request.user
        releve.save()
        messages.success(request, 'Stock physique enregistré avec succès.')
        return redirect('cellule_grain_detail', pk=cellule.pk)
    return render(request, 'maintenance/releve_cellule_form.html', {
        'cellule': cellule,
        'form': form,
    })


@login_required
def releve_cellule_update(request, pk):
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied
    releve = get_object_or_404(
        ReleveCellule.objects.select_related('cellule__site', 'cellule__silo'),
        pk=pk,
    )
    form = ReleveCelluleForm(
        request.POST or None,
        instance=releve,
        cellule=releve.cellule,
    )
    if request.method == 'POST' and form.is_valid():
        releve_corrige = form.save(commit=False)
        if 'type_grain' in form.changed_data:
            releve_corrige.poids_specifique_kg_hl = (
                releve_corrige.type_grain.poids_specifique_moyen
            )
        releve_corrige.save()
        messages.success(request, 'Stock physique corrigé avec succès.')
        return redirect('cellule_grain_detail', pk=releve.cellule_id)
    return render(request, 'maintenance/releve_cellule_form.html', {
        'cellule': releve.cellule,
        'form': form,
        'correction': True,
    })


# ─────────────────────────────────────────────
# ÉQUIPEMENTS
# ─────────────────────────────────────────────

class EquipementListView(MaintenanceRequiredMixin, ListView):
    model = Equipement
    template_name = 'maintenance/equipement_list.html'
    context_object_name = 'equipements'

    def get_queryset(self):
        sites = get_sites_utilisateur(self.request.user)
        qs = Equipement.objects.filter(site__in=sites).select_related(
            'site', 'equipement_parent'
        ).prefetch_related('sous_equipements')
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


class EquipementQrView(AdminRequiredMixin, DetailView):
    model = Equipement

    def get(self, request, *args, **kwargs):
        equipement = self.get_object()
        payload = (
            f"Équipement: {equipement.nom}\n"
            f"Site: {equipement.site.nom}\n"
            f"Référence: {equipement.reference or '—'}"
        )
        image = qrcode.make(payload)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return HttpResponse(buffer.getvalue(), content_type='image/png')


class PieceListView(AdminRequiredMixin, ListView):
    model = PieceDetachee
    template_name = 'maintenance/piece_list.html'
    context_object_name = 'pieces'
    paginate_by = 25

    def get_queryset(self):
        sites = get_sites_utilisateur(self.request.user)
        queryset = PieceDetachee.objects.filter(
            site__in=sites, actif=True).select_related('site')
        query = self.request.GET.get('q', '').strip()
        site_id = self.request.GET.get('site')
        if query:
            queryset = queryset.filter(
                Q(nom__icontains=query) | Q(reference__icontains=query))
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sites'] = get_sites_utilisateur(self.request.user)
        context['current_q'] = self.request.GET.get('q', '')
        context['current_site'] = self.request.GET.get('site', '')
        filters = self.request.GET.copy()
        filters.pop('page', None)
        context['filter_query'] = filters.urlencode()
        return context


class PieceCreateView(AdminRequiredMixin, CreateView):
    model = PieceDetachee
    form_class = PieceDetacheeForm
    template_name = 'maintenance/piece_form.html'
    success_url = reverse_lazy('piece_list')


class PieceMouvementView(AdminRequiredMixin, View):
    template_name = 'maintenance/piece_mouvement_form.html'

    def get_piece(self, **kwargs):
        sites = get_sites_utilisateur(self.request.user)
        return get_object_or_404(PieceDetachee, pk=kwargs['pk'], site__in=sites)

    def get(self, request, *args, **kwargs):
        piece = self.get_piece(**kwargs)
        return render(request, self.template_name, {'form': MouvementPieceForm(), 'object': piece})

    def post(self, request, *args, **kwargs):
        piece = self.get_piece(**kwargs)
        form = MouvementPieceForm(request.POST)
        if form.is_valid():
            mouvement = form.save(commit=False)
            mouvement.piece = piece
            mouvement.effectue_par = request.user
            if mouvement.type_mouvement == MouvementPiece.SORTIE and mouvement.quantite > piece.stock:
                form.add_error(
                    'quantite', 'La quantité sortie dépasse le stock disponible.')
            else:
                piece.stock += mouvement.quantite if mouvement.type_mouvement == MouvementPiece.ENTREE else -mouvement.quantite
                piece.save(update_fields=['stock'])
                mouvement.save()
                return redirect('piece_list')
        return render(request, self.template_name, {'form': form, 'object': piece})


# ─────────────────────────────────────────────
# PANNES
# ─────────────────────────────────────────────

def _filtered_pannes(request):
    user = request.user
    sites = get_sites_utilisateur(user)
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        return Panne.objects.none()

    if profile.is_silo():
        qs = Panne.objects.filter(signale_par=user)
    elif profile.is_maintenance():
        qs = Panne.objects.filter(affecte_a=user)
    else:
        qs = Panne.objects.filter(site__in=sites)

    if not profile.is_admin():
        qs = qs.exclude(statut=Panne.STATUT_ARCHIVEE)

    qs = qs.select_related(
        'equipement__site', 'signale_par', 'affecte_a'
    ).annotate(
        montant_total_ttc=Sum('factures__montant_ttc')
    )

    statut = request.GET.get('statut')
    priorite = request.GET.get('priorite')
    site_id = request.GET.get('site')
    q = request.GET.get('q')
    start_raw = request.GET.get('start_date')
    end_raw = request.GET.get('end_date')

    if statut:
        qs = qs.filter(statut=statut)
    if priorite:
        qs = qs.filter(priorite=priorite)
    if site_id:
        qs = qs.filter(site_id=site_id)
    if q:
        qs = qs.filter(Q(titre__icontains=q) | Q(description__icontains=q))

    try:
        start_date = date.fromisoformat(start_raw) if start_raw else None
    except ValueError:
        start_date = None
    try:
        end_date = date.fromisoformat(end_raw) if end_raw else None
    except ValueError:
        end_date = None
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date
    if start_date:
        qs = qs.filter(date_signalement__date__gte=start_date)
    if end_date:
        qs = qs.filter(date_signalement__date__lte=end_date)

    return qs.order_by('-date_signalement')


class PanneListView(LoginRequiredMixin, ListView):
    model = Panne
    template_name = 'maintenance/panne_liste.html'
    context_object_name = 'pannes'
    paginate_by = 20

    def get_queryset(self):
        return _filtered_pannes(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts'] = Panne.STATUTS
        ctx['priorites'] = Panne.PRIORITES
        ctx['sites'] = get_sites_utilisateur(self.request.user)
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_priorite'] = self.request.GET.get('priorite', '')
        ctx['current_site'] = self.request.GET.get('site', '')
        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['current_start_date'] = self.request.GET.get('start_date', '')
        ctx['current_end_date'] = self.request.GET.get('end_date', '')
        filters = self.request.GET.copy()
        filters.pop('page', None)
        ctx['filter_query'] = filters.urlencode()
        return ctx


@login_required
def panne_export_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="pannes.csv"'
    response.write('\ufeff')
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Titre', 'Site', 'Équipement',
                    'Statut', 'Priorité', 'Signalée le'])
    for panne in _filtered_pannes(request):
        writer.writerow([
            panne.titre,
            panne.site.nom,
            panne.equipement.nom if panne.equipement else '',
            panne.get_statut_display(),
            panne.get_priorite_display(),
            timezone.localtime(panne.date_signalement).strftime(
                '%d/%m/%Y %H:%M'),
        ])
    return response


# ─────────────────────────────────────────────
# RAPPORTS
# ─────────────────────────────────────────────


def _money(value):
    amount = value or Decimal('0.00')
    return f"{amount:.2f} €"


def _build_pdf_response(filename, elements):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    document.build(elements)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _report_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='SmallMuted',
               parent=styles['BodyText'], fontSize=8, leading=10, textColor=colors.HexColor('#666666')))
    styles.add(ParagraphStyle(name='SectionTitle',
               parent=styles['Heading2'], spaceBefore=8, spaceAfter=6))
    return styles


def _panne_report_pdf_elements(pannes, total_ttc, request):
    styles = _report_styles()
    elements = [
        Paragraph('Synthèse des pannes', styles['Title']),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Édité le {localdate():%d/%m/%Y} - {pannes.count()} panne(s)",
            styles['SmallMuted'],
        ),
        Spacer(1, 4 * mm),
    ]
    summary = Table(
        [['Montant TTC global des pannes', _money(total_ttc)]],
        colWidths=[110 * mm, 50 * mm],
    )
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e9ecef')),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#adb5bd')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.extend([summary, Spacer(1, 5 * mm)])

    if not pannes:
        elements.append(Paragraph(
            'Aucune panne ne correspond aux filtres sélectionnés.',
            styles['SmallMuted'],
        ))
        return elements

    rows: list[list[object]] = [[
        'Panne', 'Site', 'Statut', 'Signalée le', 'Total TTC',
    ]]
    for panne in pannes:
        rows.append([
            Paragraph(panne.titre, styles['BodyText']),
            Paragraph(panne.site.nom, styles['BodyText']),
            Paragraph(panne.get_statut_display(), styles['BodyText']),
            Paragraph(panne.date_signalement.strftime(
                '%d/%m/%Y'), styles['BodyText']),
            Paragraph(_money(panne.montant_total_ttc), styles['BodyText']),
        ])
    table = Table(rows, colWidths=[
                  48 * mm, 38 * mm, 28 * mm, 27 * mm, 25 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dee2e6')),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#adb5bd')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)
    return elements


@login_required
def panne_report(request):
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied
    pannes = _filtered_pannes(request)
    total_ttc = pannes.aggregate(total=Sum('factures__montant_ttc'))[
        'total'] or Decimal('0.00')
    return _build_pdf_response(
        f'synthese-pannes-{localdate():%Y%m%d}.pdf',
        _panne_report_pdf_elements(pannes, total_ttc, request),
    )


def _site_report_pdf_elements(context):
    styles = _report_styles()
    elements = [Paragraph('Rapport d\'activités par site', styles['Title']), Spacer(
        1, 4 * mm), Paragraph(context['period_label'], styles['SmallMuted']), Spacer(1, 6 * mm)]

    for index, site_info in enumerate(context['sites_data']):
        elements.append(Paragraph(site_info['site'].nom, styles['Heading1']))
        elements.append(Paragraph(
            f"Adresse : {site_info['site'].adresse or 'N/A'}", styles['BodyText']))
        elements.append(Paragraph(
            f"Adresse complémentaire : {site_info['site'].adresse or 'N/A'}", styles['BodyText']))
        elements.append(Spacer(1, 3 * mm))

        summary_rows = [
            ['Pannes terminées', str(site_info['pannes_terminees_count'])],
            ['Montant TTC des factures liées', _money(
                site_info['pannes_terminees_total_ttc'])],
            ['Total des factures', str(site_info['facture_summary']['total'])],
            ['Montant total TTC', _money(
                site_info['facture_summary']['montant_total_ttc'])],
        ]
        summary_table = Table(summary_rows, colWidths=[85 * mm, 75 * mm])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#ced4da')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 5 * mm))

        elements.append(
            Paragraph('Pannes terminées et factures associées', styles['SectionTitle']))
        if site_info['pannes_terminees']:
            rows: list[list[object]] = [
                ['Panne', 'Terminée le', 'Factures', 'Total TTC']]
            for panne in site_info['pannes_terminees']:
                facture_lines = '<br/>'.join(
                    f"{facture.numero} - {_money(facture.montant_ttc)}"
                    for facture in Facture.objects.filter(panne=panne)
                ) or 'Aucune facture liée'
                rows.append([
                    Paragraph(panne.titre, styles['BodyText']),
                    Paragraph(panne.date_resolution.strftime(
                        '%d/%m/%Y %H:%M') if panne.date_resolution else '—', styles['BodyText']),
                    Paragraph(facture_lines, styles['BodyText']),
                    Paragraph(
                        _money(getattr(panne, 'montant_factures_ttc', None)), styles['BodyText']),
                ])
            table = Table(rows, colWidths=[
                          42 * mm, 30 * mm, 78 * mm, 30 * mm], repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dee2e6')),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#adb5bd')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ]))
            elements.append(table)
        else:
            elements.append(
                Paragraph('Aucune panne terminée sur cette période.', styles['SmallMuted']))

        if index < len(context['sites_data']) - 1:
            elements.append(PageBreak())

    return elements


def _period_report_pdf_elements(context):
    styles = _report_styles()
    elements = [Paragraph('Rapport d\'activité', styles['Title']), Spacer(1, 4 * mm), Paragraph(
        context['period_label'], styles['SmallMuted']), Spacer(1, 6 * mm)]

    for index, site_info in enumerate(context['sites_data']):
        elements.append(Paragraph(site_info['site'].nom, styles['Heading1']))
        elements.append(Paragraph(
            f"Pannes terminées : {site_info['panne_count']}", styles['BodyText']))
        elements.append(Paragraph(
            f"Total TTC des factures liées : {_money(site_info['total_pannes_ttc'])}", styles['BodyText']))
        elements.append(Spacer(1, 3 * mm))

        if site_info['pannes']:
            rows: list[list[object]] = [
                ['Panne', 'Terminée le', 'Factures', 'Total TTC']]
            for panne in site_info['pannes']:
                facture_lines = '<br/>'.join(
                    f"{facture.numero} - {_money(facture.montant_ttc)}"
                    for facture in Facture.objects.filter(panne=panne)
                ) or 'Aucune facture liée'
                rows.append([
                    Paragraph(panne.titre, styles['BodyText']),
                    Paragraph(panne.date_resolution.strftime(
                        '%d/%m/%Y %H:%M') if panne.date_resolution else '—', styles['BodyText']),
                    Paragraph(facture_lines, styles['BodyText']),
                    Paragraph(
                        _money(getattr(panne, 'montant_factures_ttc', None)), styles['BodyText']),
                ])
            table = Table(rows, colWidths=[
                          42 * mm, 30 * mm, 78 * mm, 30 * mm], repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dee2e6')),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#adb5bd')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ]))
            elements.append(table)
        else:
            elements.append(
                Paragraph('Aucune panne terminée sur cette période.', styles['SmallMuted']))

        if index < len(context['sites_data']) - 1:
            elements.append(PageBreak())

    return elements


def _report_period_from_request(request):
    today = localdate()
    default_start = today.replace(day=1)
    params = request.POST if request.method == 'POST' else request.GET
    start_raw = params.get('start_date', '')
    end_raw = params.get('end_date', '')

    try:
        start_date = date.fromisoformat(
            start_raw) if start_raw else default_start
    except ValueError:
        start_date = default_start

    try:
        end_date = date.fromisoformat(end_raw) if end_raw else today
    except ValueError:
        end_date = today

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return start_date, end_date


class SiteReportView(AdminRequiredMixin, ListView):
    template_name = 'maintenance/site_report.html'
    context_object_name = 'sites_data'

    def get_queryset(self):
        site_id = self.kwargs.get('pk') or self.request.GET.get('site')
        if site_id:
            return Site.objects.filter(pk=site_id).order_by('nom')
        return Site.objects.all().order_by('nom')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sites_data = []
        statuts_termines = [Panne.STATUT_TERMINEE, Panne.STATUT_ARCHIVEE]
        start_date, end_date = _report_period_from_request(self.request)
        selected_site = self.kwargs.get(
            'pk') or self.request.GET.get('site', '')

        for site in context['sites_data']:
            equipements = site.equipements.all().prefetch_related(
                'pannes', 'maintenances_preventives')

            pannes_site = Panne.objects.filter(site=site).select_related(
                'site', 'equipement__site', 'signale_par', 'affecte_a'
            ).prefetch_related('factures')
            pannes_terminees = pannes_site.filter(statut__in=statuts_termines).annotate(
                montant_factures_ttc=Sum('factures__montant_ttc')
            ).filter(
                date_resolution__date__range=(start_date, end_date)
            ).order_by('-date_resolution', '-date_signalement')
            preventives_site = MaintenancePreventive.objects.filter(
                Q(site=site) | Q(equipement__site=site))
            factures_site = Facture.objects.filter(
                Q(panne__site=site) | Q(
                    preventive__site=site) | Q(
                    preventive__equipement__site=site)
            ).distinct()
            factures_pannes_terminees = Facture.objects.filter(
                panne__site=site,
                panne__statut__in=statuts_termines,
                panne__date_resolution__date__range=(start_date, end_date),
            )

            site_info = {
                'site': site,
                'equipements': [],
                'panne_summary': {
                    'total': pannes_site.count(),
                    'nouvelles': pannes_site.filter(statut=Panne.STATUT_NOUVELLE).count(),
                    'affectees': pannes_site.filter(statut=Panne.STATUT_AFFECTEE).count(),
                    'en_cours': pannes_site.filter(statut=Panne.STATUT_EN_COURS).count(),
                    'terminees': pannes_site.filter(statut=Panne.STATUT_TERMINEE).count(),
                    'archivees': pannes_site.filter(statut=Panne.STATUT_ARCHIVEE).count(),
                    'annulees': pannes_site.filter(statut=Panne.STATUT_ANNULEE).count(),
                    'critiques': pannes_site.filter(priorite=Panne.PRIORITE_CRITIQUE).count(),
                },
                'preventive_summary': {
                    'total': preventives_site.count(),
                    'planifiees': preventives_site.filter(statut=MaintenancePreventive.STATUT_PLANIFIEE).count(),
                    'en_retard': preventives_site.filter(statut=MaintenancePreventive.STATUT_EN_RETARD).count(),
                    'effectuees': preventives_site.filter(statut=MaintenancePreventive.STATUT_EFFECTUEE).count(),
                    'validees': preventives_site.filter(statut=MaintenancePreventive.STATUT_VALIDEE).count(),
                    'annulees': preventives_site.filter(statut=MaintenancePreventive.STATUT_ANNULEE).count(),
                },
                'facture_summary': {
                    'total': factures_site.count(),
                    'montant_total_ttc': factures_site.aggregate(Sum('montant_ttc'))['montant_ttc__sum'] or Decimal('0.00'),
                },
                'pannes_terminees': pannes_terminees,
                'pannes_terminees_count': pannes_terminees.count(),
                'pannes_terminees_total_ttc': factures_pannes_terminees.aggregate(Sum('montant_ttc'))['montant_ttc__sum'] or Decimal('0.00'),
            }

            for eq in equipements:
                pannes_equipement = eq.pannes.filter(
                    statut__in=statuts_termines,
                    date_resolution__date__range=(start_date, end_date),
                ).select_related('signale_par', 'affecte_a').prefetch_related('factures').annotate(
                    montant_factures_ttc=Sum('factures__montant_ttc')
                ).order_by('-date_resolution', '-date_signalement')
                site_info['equipements'].append({
                    'equipement': eq,
                    'pannes': pannes_equipement,
                    'preventives': eq.maintenances_preventives.all().select_related(
                        'affecte_a', 'created_by'),
                })
            sites_data.append(site_info)

        context['sites_data'] = sites_data
        context['period_start'] = start_date
        context['period_end'] = end_date
        context['period_label'] = f"du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}"
        context['selected_site'] = selected_site
        context['sites'] = Site.objects.all().order_by('nom')
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'pdf':
            filename = f'rapport-sites-{context["period_start"]:%Y%m%d}-{context["period_end"]:%Y%m%d}.pdf'
            return _build_pdf_response(filename, _site_report_pdf_elements(context))
        return super().render_to_response(context, **response_kwargs)


@login_required
def report_selector(request):
    """Affiche un formulaire pour sélectionner la période du rapport."""
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied
    today = localdate()
    default_start = today.replace(day=1)
    if request.method == 'POST':
        start_date, end_date = _report_period_from_request(request)
        site_id = request.POST.get('site')
        query = f'start_date={start_date:%Y-%m-%d}&end_date={end_date:%Y-%m-%d}'
        if site_id:
            query += f'&site={site_id}'
        return redirect(f'{reverse("period_report")}?{query}')

    return render(
        request,
        'maintenance/report_selector.html',
        {
            'sites': Site.objects.all().order_by('nom'),
            'current_site': request.POST.get('site', ''),
            'default_start': default_start,
            'default_end': today,
            'current_year': today.year,
            'current_month': today.month,
        },
    )


class PeriodReportView(AdminRequiredMixin, ListView):
    template_name = 'maintenance/monthly_report.html'
    context_object_name = 'sites_data'

    def get_queryset(self):
        qs = Site.objects.all().order_by('nom')
        site_id = self.request.GET.get('site')
        if site_id:
            qs = qs.filter(pk=site_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = _report_period_from_request(self.request)
        site_id = self.request.GET.get('site', '')
        statuts_termines = [Panne.STATUT_TERMINEE, Panne.STATUT_ARCHIVEE]

        sites_data = []
        for site in context['sites_data']:
            pannes = Panne.objects.filter(
                site=site,
                date_resolution__date__range=(start_date, end_date),
                statut__in=statuts_termines,
            ).select_related('equipement__site', 'signale_par', 'affecte_a').prefetch_related('factures').annotate(
                montant_factures_ttc=Sum('factures__montant_ttc')
            ).order_by('-date_resolution', '-date_signalement')
            preventives = MaintenancePreventive.objects.filter(
                Q(site=site) | Q(equipement__site=site),
                date_echeance__date__range=(start_date, end_date),
            )
            total_pannes_ttc = pannes.aggregate(total=Sum('factures__montant_ttc'))[
                'total'] or Decimal('0.00')

            site_info = {
                'site': site,
                'pannes': pannes,
                'preventives': preventives,
                'panne_count': pannes.count(),
                'preventive_count': preventives.count(),
                'total_pannes_ttc': total_pannes_ttc,
            }
            sites_data.append(site_info)

        context['sites_data'] = sites_data
        context['period_start'] = start_date
        context['period_end'] = end_date
        context['period_label'] = (
            f"Du {start_date:%d/%m/%Y} au {end_date:%d/%m/%Y}"
        )
        context['current_site'] = site_id
        context['sites'] = Site.objects.all().order_by('nom')
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'pdf':
            filename = f'rapport-periode-{context["period_start"]:%Y%m%d}-{context["period_end"]:%Y%m%d}.pdf'
            return _build_pdf_response(filename, _period_report_pdf_elements(context))
        return super().render_to_response(context, **response_kwargs)


class MonthlyReportView(PeriodReportView):
    def dispatch(self, request, *args, **kwargs):
        year = int(kwargs['year'])
        month = int(kwargs['month'])
        month_start = date(year, month, 1)
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        query = request.GET.copy()
        query['start_date'] = month_start.isoformat()
        query['end_date'] = (next_month - timedelta(days=1)).isoformat()
        request.GET = query
        return super().dispatch(request, *args, **kwargs)


def _transitions_panne_pour_utilisateur(panne, user, profile):
    if profile.is_admin():
        return Panne.TRANSITIONS_AUTORISEES.get(panne.statut, [])
    if profile.is_maintenance() and panne.affecte_a_id == user.id:
        return [
            statut
            for statut in Panne.TRANSITIONS_AUTORISEES.get(panne.statut, [])
            if statut != Panne.Statut.CLOTUREE
        ]
    return []


def _utilisateur_peut_acceder_panne(panne, user, profile):
    if profile.is_admin():
        return True
    if panne.statut == Panne.STATUT_ARCHIVEE:
        return False
    if profile.is_silo():
        return panne.signale_par_id == user.id
    if profile.is_maintenance():
        return panne.affecte_a_id == user.id
    return False


class PanneDetailView(LoginRequiredMixin, DetailView):
    model = Panne
    template_name = 'maintenance/panne_detail.html'
    context_object_name = 'panne'
    object: Panne

    def get_object(self):
        obj = cast(Panne, super().get_object())
        user = self.request.user
        try:
            profile = Profile.objects.get(user=user)
        except Profile.DoesNotExist:
            raise PermissionDenied
        if not _utilisateur_peut_acceder_panne(obj, user, profile):
            raise PermissionDenied
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        panne = cast(Panne, self.object)
        user = self.request.user
        ctx['historique'] = HistoriquePanne.objects.filter(panne=panne)
        ctx['medias'] = PanneMedia.objects.filter(panne=panne)
        try:
            profile = Profile.objects.get(user=user)
        except Profile.DoesNotExist:
            profile = None
        ctx['profile'] = profile
        ctx['can_edit_panne'] = bool(
            profile
            and profile.is_silo()
            and panne.signale_par_id == user.id
            and panne.statut == Panne.Statut.NOUVELLE
        )
        if profile and profile.is_admin():
            ctx['factures'] = Facture.objects.filter(panne=panne)
            ctx['total_factures_ht'] = ctx['factures'].aggregate(
                total=Sum('montant_ht')
            )['total'] or Decimal('0.00')
        else:
            ctx['factures'] = Facture.objects.none()
            ctx['total_factures_ht'] = Decimal('0.00')

        if profile and not profile.is_silo():
            transitions = _transitions_panne_pour_utilisateur(
                panne, user, profile)
            ctx['statut_form'] = PanneStatutForm(
                panne=panne, transitions=transitions)
            ctx['transitions_autorisees'] = [
                (statut, dict(Panne.STATUTS).get(statut, statut))
                for statut in transitions
            ]
            if profile.is_admin():
                ctx['affectation_form'] = PanneAffectationForm(instance=panne)
                ctx['priorite_form'] = PannePrioriteForm(instance=panne)

        if profile and (
            profile.is_admin() or (profile.is_maintenance() and panne.affecte_a == user)
        ):
            ctx['afficher_temps_intervention'] = True
            ctx['temps_intervention_form'] = (
                PanneTempsInterventionForm() if panne.affecte_a_id else None
            )
            ctx['temps_interventions'] = panne.temps_interventions.select_related(
                'agent').order_by('-date_intervention', '-creee_le')
            ctx['total_temps_minutes'] = panne.total_temps_minutes
            ctx['cout_total_intervention'] = panne.cout_total_intervention
            ctx['cout_total_global'] = panne.cout_total_global
        return ctx


@login_required
@require_POST
def panne_ajouter_temps_intervention(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not (profile.is_admin() or profile.is_maintenance()):
        raise PermissionDenied
    if not panne.affecte_a_id:
        raise PermissionDenied
    if profile.is_maintenance() and panne.affecte_a != request.user:
        raise PermissionDenied

    form = PanneTempsInterventionForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors.as_text())
        return redirect('panne_detail', pk=pk)

    PanneTempsIntervention.objects.create(
        panne=panne,
        agent=panne.affecte_a if profile.is_admin() else request.user,
        date_intervention=form.cleaned_data['date_intervention'],
        duree_minutes=form.cleaned_data['duree_minutes'],
        commentaire=form.cleaned_data['commentaire'],
        validee=profile.is_admin(),
    )
    messages.success(request, 'Temps d’intervention enregistré.')
    return redirect('panne_detail', pk=pk)


@login_required
@require_POST
def panne_valider_temps_intervention(request, pk, temps_pk):
    panne = get_object_or_404(Panne, pk=pk)
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied

    temps = get_object_or_404(PanneTempsIntervention, pk=temps_pk, panne=panne)
    temps.validee = True
    temps.save(update_fields=['validee'])
    messages.success(request, 'Temps d’intervention validé.')
    return redirect('panne_detail', pk=pk)


class PanneCreateView(SiloRequiredMixin, CreateView):
    model = Panne
    form_class = PanneForm
    template_name = 'maintenance/panne_form.html'
    object: Panne

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.signale_par = self.request.user
        response = super().form_valid(form)
        panne = cast(Panne, self.object)
        for fichier in (*form.cleaned_data['photos'], *form.cleaned_data['videos']):
            PanneMedia.objects.create(
                panne=panne,
                fichier=fichier,
                nom_original=fichier.name,
                ajoute_par=self.request.user,
            )
        messages.success(self.request, 'Panne signalée avec succès.')
        return response

    def get_success_url(self):
        return reverse('panne_detail', kwargs={'pk': self.object.pk})


class PanneUpdateView(LoginRequiredMixin, UpdateView):
    model = Panne
    form_class = PanneForm
    template_name = 'maintenance/panne_form.html'
    object: Panne

    def get_queryset(self):
        profile = Profile.objects.filter(user=self.request.user).first()
        if not profile or not profile.is_silo():
            return Panne.objects.none()
        return Panne.objects.filter(
            signale_par=self.request.user,
            statut=Panne.Statut.NOUVELLE,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        panne = cast(Panne, self.object)
        for fichier in (*form.cleaned_data['photos'], *form.cleaned_data['videos']):
            PanneMedia.objects.create(
                panne=panne,
                fichier=fichier,
                nom_original=fichier.name,
                ajoute_par=self.request.user,
            )
        messages.success(self.request, 'Panne modifiée avec succès.')
        return response

    def get_success_url(self):
        return reverse('panne_detail', kwargs={'pk': self.object.pk})


class PanneDeleteView(LoginRequiredMixin, DeleteView):
    model = Panne
    template_name = 'maintenance/confirm_delete.html'
    success_url = reverse_lazy('panne_liste')

    def get_queryset(self):
        user = self.request.user
        try:
            profile = Profile.objects.get(user=user)
        except Profile.DoesNotExist:
            return Panne.objects.none()

        if profile.is_admin():
            return Panne.objects.select_related('equipement__site')
        if profile.is_silo():
            return Panne.objects.filter(
                signale_par=user,
                statut=Panne.Statut.NOUVELLE,
            ).select_related('site', 'equipement')
        return Panne.objects.none()

    def form_valid(self, form):
        panne = cast(Panne, self.get_object())
        for media in PanneMedia.objects.filter(panne=panne):
            media.fichier.delete(save=False)
        for facture in Facture.objects.filter(panne=panne):
            facture.fichier.delete(save=False)
        panne.delete()
        messages.success(self.request, 'Panne et fichiers associés supprimés.')
        return redirect(self.get_success_url())


@login_required
@require_POST
def panne_changer_statut(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        raise PermissionDenied

    transitions = _transitions_panne_pour_utilisateur(
        panne, request.user, profile)
    if request.POST.get('nouveau_statut') not in transitions:
        raise PermissionDenied

    form = PanneStatutForm(
        request.POST,
        request.FILES,
        panne=panne,
        transitions=transitions,
    )
    if form.is_valid():
        try:
            panne.changer_statut(
                form.cleaned_data['nouveau_statut'],
                request.user,
                form.cleaned_data.get('commentaire', ''),
            )
            for fichier in form.cleaned_data['medias']:
                PanneMedia.objects.create(
                    panne=panne,
                    fichier=fichier,
                    nom_original=fichier.name,
                    ajoute_par=request.user,
                )
            messages.success(request, 'Statut mis à jour.')
        except ValueError as e:
            messages.error(request, str(e))
    return redirect('panne_detail', pk=pk)


@login_required
@require_POST
def panne_ajouter_facture(request, pk):
    panne = get_object_or_404(
        Panne,
        pk=pk,
        site__in=get_sites_utilisateur(request.user),
    )
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied

    if request.method == 'POST':
        form = FactureForm(
            request.POST,
            request.FILES,
            user=request.user,
            panne=panne,
        )
        if form.is_valid():
            facture = form.save(commit=False)
            facture.panne = panne
            facture.preventive = None
            facture.created_by = request.user
            fichier = form.cleaned_data.get('fichier_upload')
            if fichier:
                facture.fichier = fichier
                facture.nom_fichier_original = fichier.name
            facture.save()
            messages.success(request, 'Facture ajoutée.')
        else:
            messages.error(request, form.errors.as_text())
    return redirect('panne_detail', pk=pk)


@login_required
def panne_ajouter_facture_pdf(request, pk):
    panne = get_object_or_404(
        Panne,
        pk=pk,
        site__in=get_sites_utilisateur(request.user),
    )
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied

    if request.method == 'POST':
        form = FacturePdfUploadForm(request.POST, request.FILES)
        if form.is_valid():
            factures = form.save(panne=panne, user=request.user)
            messages.success(
                request, f'{len(factures)} facture(s) importée(s).')
            return redirect('panne_detail', pk=pk)
        else:
            messages.error(request, form.errors.as_text())
    else:
        form = FacturePdfUploadForm()
    return render(request, 'maintenance/facture_pdf_form.html', {
        'panne': panne,
        'form': form,
    })


def _facture_panne_autorisee(request, pk, facture_pk=None):
    panne = get_object_or_404(
        Panne,
        pk=pk,
        site__in=get_sites_utilisateur(request.user),
    )
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied
    if facture_pk is None:
        return panne, None
    facture = get_object_or_404(Facture, pk=facture_pk, panne=panne)
    return panne, facture


@login_required
def panne_modifier_facture(request, pk, facture_pk):
    panne, facture = _facture_panne_autorisee(request, pk, facture_pk)
    facture = cast(Facture, facture)
    if request.method == 'POST':
        form = FactureForm(
            request.POST,
            request.FILES,
            instance=facture,
            user=request.user,
            panne=panne,
        )
        if form.is_valid():
            facture = form.save(commit=False)
            facture.panne = panne
            facture.preventive = None
            fichier = form.cleaned_data.get('fichier_upload')
            if fichier:
                if facture.fichier:
                    facture.fichier.delete(save=False)
                facture.fichier = fichier
                facture.nom_fichier_original = fichier.name
            facture.save()
            messages.success(request, 'Facture mise à jour.')
            return redirect('panne_detail', pk=panne.pk)
    else:
        form = FactureForm(
            instance=facture,
            user=request.user,
            panne=panne,
        )
    return render(request, 'maintenance/facture_form.html', {
        'form': form,
        'facture': facture,
        'panne': panne,
    })


@login_required
@require_POST
def panne_valider_facture(request, pk, facture_pk):
    panne, facture = _facture_panne_autorisee(request, pk, facture_pk)
    facture = cast(Facture, facture)
    if request.method != 'POST':
        raise PermissionDenied
    facture.statut = Facture.STATUT_VALIDE
    facture.save(update_fields=['statut', 'validee', 'modifiee_le'])
    messages.success(request, 'Facture validée.')
    return redirect('panne_detail', pk=panne.pk)


@login_required
@require_POST
def panne_supprimer_facture(request, pk, facture_pk):
    panne, facture = _facture_panne_autorisee(request, pk, facture_pk)
    facture = cast(Facture, facture)
    if request.method != 'POST':
        raise PermissionDenied
    if facture.fichier:
        facture.fichier.delete(save=False)
    facture.delete()
    messages.success(request, 'Facture supprimée.')
    return redirect('panne_detail', pk=panne.pk)


@login_required
@require_POST
def panne_affecter(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        raise PermissionDenied

    if not profile.is_admin():
        raise PermissionDenied

    if request.method == 'POST':
        form = PanneAffectationForm(request.POST, instance=panne)
        if form.is_valid():
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
            supprimer_notifications_declaration_panne(panne)
            notifier_affectation_panne(panne)
            messages.success(request, 'Panne affectée.')
        else:
            messages.error(
                request, 'Sélectionnez un technicien pour affecter la panne.')
    return redirect('panne_detail', pk=pk)


@login_required
@require_POST
def panne_modifier_priorite(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied

    form = PannePrioriteForm(request.POST, instance=panne)
    if form.is_valid():
        panne.priorite = form.cleaned_data['priorite']
        panne.save(update_fields=['priorite', 'updated_at'])
        messages.success(request, 'Priorité de la panne mise à jour.')
    else:
        messages.error(request, 'Sélectionnez une priorité valide.')
    return redirect('panne_detail', pk=pk)


@login_required
@require_POST
def panne_ajouter_media(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        raise PermissionDenied
    if not _utilisateur_peut_acceder_panne(panne, request.user, profile):
        raise PermissionDenied
    if request.method == 'POST':
        form = PanneMediaForm(request.POST, request.FILES)
        if form.is_valid():
            for fichier in form.cleaned_data['medias']:
                PanneMedia.objects.create(
                    panne=panne,
                    fichier=fichier,
                    nom_original=fichier.name,
                    ajoute_par=request.user,
                )
            messages.success(request, 'Photo ou vidéo terrain ajoutée.')
    return redirect('panne_detail', pk=pk)


@login_required
def panne_media_telecharger(request, pk):
    media = get_object_or_404(
        PanneMedia.objects.select_related('panne'), pk=pk)
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        raise PermissionDenied
    if not _utilisateur_peut_acceder_panne(media.panne, request.user, profile):
        raise PermissionDenied
    media.fichier.open('rb')
    return FileResponse(
        media.fichier,
        as_attachment=True,
        filename=media.nom_telechargement,
    )


@login_required
def panne_media_prive(request, chemin):
    media = get_object_or_404(
        PanneMedia.objects.select_related('panne'),
        fichier=f'pannes/{chemin}',
    )
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        raise PermissionDenied
    if not _utilisateur_peut_acceder_panne(media.panne, request.user, profile):
        raise PermissionDenied
    media.fichier.open('rb')
    return FileResponse(
        media.fichier,
        as_attachment=True,
        filename=media.nom_telechargement,
    )


class PanneMediaDeleteView(MaintenanceRequiredMixin, DeleteView):
    model = PanneMedia
    template_name = 'maintenance/confirm_file_delete.html'
    context_object_name = 'media'

    def get_queryset(self):
        sites = get_sites_utilisateur(self.request.user)
        return PanneMedia.objects.filter(
            panne__site__in=sites
        ).select_related('panne')

    def get_success_url(self):
        media = self.get_object()
        assert isinstance(media, PanneMedia)
        panne_pk = getattr(media, 'panne_id', media.panne.pk)
        return reverse('panne_detail', kwargs={'pk': panne_pk})

    def form_valid(self, form):
        media = self.get_object()
        assert isinstance(media, PanneMedia)
        panne_pk = getattr(media, 'panne_id', media.panne.pk)
        media.fichier.delete(save=False)
        media.delete()
        messages.success(self.request, 'Fichier supprimé.')
        return redirect('panne_detail', pk=panne_pk)


@login_required
@require_POST
def panne_ajouter_factures(request, pk):
    panne = get_object_or_404(Panne, pk=pk)
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        form = PanneFactureUploadForm(request.POST, request.FILES)
        if form.is_valid():
            fichiers = (*form.cleaned_data['photos'],
                        *form.cleaned_data['pdfs'])
            factures_creees = 0
            total_detecte = Decimal('0.00')
            factures_sans_ttc = 0
            for fichier in fichiers:
                if extract_invoice_data_from_document is not None:
                    invoice_data = extract_invoice_data_from_document(
                        fichier) or {}
                else:
                    invoice_data = {}

                invoice_data = invoice_data if isinstance(
                    invoice_data, dict) else {}
                montant_ttc = invoice_data.get('montant_ttc')
                details_detection = invoice_data.get('_detection', {})
                score_detection = int(
                    details_detection.get('score_global', 0))
                detection_complete = (
                    score_detection >= 80
                    and not details_detection.get('alertes')
                )

                numero_detecte = invoice_data.get('numero')
                if numero_detecte and Facture.objects.filter(numero=numero_detecte).exists():
                    PanneMedia.objects.create(
                        panne=panne,
                        fichier=fichier,
                        nom_original=f'Doublon de facture - {fichier.name}',
                        ajoute_par=request.user,
                    )
                    continue
                numero = numero_detecte
                if not numero:
                    numero = f'AUTO-{panne.pk}-{uuid4().hex[:12].upper()}'
                fournisseur = invoice_data.get('fournisseur') or 'À compléter'
                date_facture = invoice_data.get('date_facture') or localdate()
                if montant_ttc is None:
                    montant_ttc = Decimal('0.00')
                    factures_sans_ttc += 1
                montant_ht = invoice_data.get('montant_ht')
                if montant_ht is None:
                    montant_ht = montant_ttc
                montant_tva = invoice_data.get(
                    'montant_tva', Decimal('0.00'))
                taux_tva = invoice_data.get('taux_tva', Decimal('0.00'))
                Facture.objects.create(
                    panne=panne,
                    numero=numero,
                    fournisseur=fournisseur,
                    type_facture=Facture.TYPE_AUTRE,
                    statut=Facture.STATUT_BROUILLON,
                    statut_detection=(
                        Facture.DETECTION_OK if detection_complete
                        else Facture.DETECTION_INCOMPLETE
                    ),
                    score_detection=score_detection,
                    details_detection=details_detection,
                    montant_ht=montant_ht,
                    taux_tva=taux_tva,
                    montant_tva=montant_tva,
                    montant_ttc=montant_ttc,
                    date_facture=date_facture,
                    description=(
                        invoice_data.get('description_detectee')
                        or (
                            'Toutes les informations ont été détectées automatiquement. Vérifiez-les avant validation.'
                            if detection_complete else
                            'Détection partielle. Complétez ou vérifiez les informations de la facture.'
                        )
                    ),
                    fichier=fichier,
                    created_by=request.user,
                )
                factures_creees += 1
                total_detecte += montant_ttc

            if factures_creees:
                messages.success(
                    request,
                    f'{factures_creees} facture(s) brouillon créée(s), pour un total TTC détecté de {total_detecte:.2f} €.',
                )
            if factures_sans_ttc:
                messages.info(
                    request,
                    f'{factures_sans_ttc} facture(s) nécessitent la saisie manuelle du TTC.',
                )
            if factures_creees != len(fichiers):
                messages.info(
                    request,
                    'Les fichiers avec un numéro de facture déjà existant ont été ajoutés comme pièces jointes.',
                )
        else:
            messages.error(request, form.errors.as_text())
    return redirect('panne_detail', pk=pk)


# ─────────────────────────────────────────────
# MAINTENANCES PRÉVENTIVES
# ─────────────────────────────────────────────

class PreventiveListView(AdminSiloMaintenanceRequiredMixin, ListView):
    model = MaintenancePreventive
    template_name = 'maintenance/preventive_liste.html'
    context_object_name = 'preventives'
    paginate_by = 20

    def get_queryset(self):
        profile = Profile.objects.filter(user=self.request.user).first()
        sites = get_sites_utilisateur(self.request.user)
        qs = MaintenancePreventive.objects.filter(
            Q(site__in=sites) | Q(equipement__site__in=sites)
        ).select_related('site', 'equipement__site', 'affecte_a')

        if profile and profile.is_silo():
            qs = qs.filter(affecte_a=self.request.user).exclude(
                statut=MaintenancePreventive.Statut.ARCHIVEE,
            )
        elif profile and profile.is_maintenance():
            qs = qs.filter(
                equipement_id__in=_pannes_actives_affectees(
                    self.request.user
                ).exclude(equipement__isnull=True).values("equipement_id")
            ).distinct()

        statut = self.request.GET.get('statut')
        periodicite = self.request.GET.get('periodicite')
        site_id = self.request.GET.get('site')
        q = self.request.GET.get('q')

        if statut:
            qs = qs.filter(statut=statut)
        if periodicite:
            qs = qs.filter(periodicite=periodicite)
        if site_id:
            qs = qs.filter(Q(site_id=site_id) | Q(equipement__site_id=site_id))
        if q:
            qs = qs.filter(Q(titre__icontains=q) | Q(description__icontains=q))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts'] = MaintenancePreventive.STATUTS
        ctx['periodicites'] = MaintenancePreventive.Periodicite.choices
        ctx['sites'] = get_sites_utilisateur(self.request.user)
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_periodicite'] = self.request.GET.get('periodicite', '')
        ctx['current_site'] = self.request.GET.get('site', '')
        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['today'] = localdate()
        filters = self.request.GET.copy()
        filters.pop('page', None)
        ctx['filter_query'] = filters.urlencode()
        return ctx


class PreventiveCalendarView(AdminSiloMaintenanceRequiredMixin, TemplateView):
    template_name = 'maintenance/preventive_calendrier.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sites = get_sites_utilisateur(self.request.user)
        today = localdate()
        try:
            year = int(self.request.GET.get('year', today.year))
            month = int(self.request.GET.get('month', today.month))
            if month < 1 or month > 12:
                raise ValueError
            month_start = date(year, month, 1)
        except (TypeError, ValueError):
            year, month = today.year, today.month
            month_start = date(year, month, 1)
        next_month = date(
            year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        preventives = MaintenancePreventive.objects.filter(
            Q(site__in=sites) | Q(equipement__site__in=sites),
            date_echeance__date__gte=month_start,
            date_echeance__date__lt=next_month,
        ).exclude(statut=MaintenancePreventive.Statut.ARCHIVEE).select_related(
            'site', 'equipement'
        )
        vehicles = Vehicule.objects.filter(site__in=sites).exclude(
            statut=Vehicule.Statut.CEDE
        ).select_related('site')
        events = [
            {
                'date': preventive.date_echeance.date(),
                'title': preventive.titre,
                'kind': 'preventive',
                'label': preventive.get_statut_display(),
                'url': reverse('preventive_detail', args=[preventive.pk]),
            }
            for preventive in preventives
        ]
        profile = Profile.objects.filter(user=self.request.user).first()
        for vehicle in vehicles:
            for field_name, label in (
                ('date_assurance', 'Assurance'),
                ('date_controle_technique', 'Contrôle technique'),
                ('date_vgp', 'VGP'),
                ('date_mines', 'Passage aux mines'),
                ('prochain_entretien_date', 'Entretien véhicule'),
            ):
                event_date = getattr(vehicle, field_name, None)
                if event_date and month_start <= event_date < next_month:
                    events.append({
                        'date': event_date,
                        'title': f'{label} · {vehicle}',
                        'kind': 'vehicule',
                        'label': vehicle.site.nom,
                        'url': (
                            reverse('vehicules:detail', args=[vehicle.pk])
                            if profile and profile.is_admin() else None
                        ),
                    })
        events.sort(key=lambda event: (
            event['date'], event['kind'], event['title']))
        context.update({
            'events': events,
            'month_start': month_start,
            'year': year,
            'month': month,
            'previous_month': month_start - timedelta(days=1),
            'next_month': next_month,
        })
        return context


class PreventiveDetailView(LoginRequiredMixin, DetailView):
    model = MaintenancePreventive
    template_name = 'maintenance/preventive_detail.html'
    context_object_name = 'preventive'
    object: MaintenancePreventive

    def get_queryset(self):
        profile = Profile.objects.filter(user=self.request.user).first()
        if not profile:
            return MaintenancePreventive.objects.none()
        sites = get_sites_utilisateur(self.request.user)
        qs = MaintenancePreventive.objects.filter(
            Q(site__in=sites) | Q(equipement__site__in=sites)
        ).select_related('site', 'equipement__site', 'affecte_a')
        if profile.is_admin():
            return qs
        if profile.is_silo():
            qs = qs.filter(affecte_a=self.request.user).exclude(
                statut=MaintenancePreventive.Statut.ARCHIVEE,
            )
        elif profile.is_maintenance():
            qs = qs.filter(
                equipement_id__in=_pannes_actives_affectees(
                    self.request.user
                ).exclude(equipement__isnull=True).values('equipement_id')
            )
        else:
            return MaintenancePreventive.objects.none()
        return qs.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        preventive = self.object
        profile = Profile.objects.filter(user=self.request.user).first()
        allowed_statuses = None
        status_labels = None
        can_manage_preventive = bool(profile and profile.is_admin())
        can_execute_preventive = preventive.affecte_a_id == self.request.user.id
        can_validate_preventive = bool(
            profile and (
                profile.is_admin() or (
                    profile.is_maintenance()
                    and _maintenance_peut_valider_preventive(
                        self.request.user, preventive)
                )
            )
        )
        can_complete_preventive = bool(
            profile
            and profile.is_maintenance()
            and _maintenance_peut_valider_preventive(
                self.request.user, preventive)
            and MaintenancePreventive.STATUT_EFFECTUEE
            in MaintenancePreventive.TRANSITIONS_AUTORISEES.get(
                preventive.statut, [])
        )
        if profile and profile.is_silo():
            allowed_statuses = {
                MaintenancePreventive.STATUT_PRISE_EN_COMPTE,
                MaintenancePreventive.STATUT_EN_ATTENTE,
                MaintenancePreventive.STATUT_EFFECTUEE,
            }
            status_labels = {
                MaintenancePreventive.STATUT_EN_ATTENTE: 'Problème',
            }
        elif profile and profile.is_maintenance():
            allowed_statuses = None
        ctx['historique'] = HistoriquePreventive.objects.filter(
            preventive=preventive)
        ctx['medias'] = PreventiveMedia.objects.filter(preventive=preventive)
        ctx['factures'] = (
            Facture.objects.filter(preventive=preventive)
            if profile and profile.is_admin()
            else Facture.objects.none()
        )
        ctx['can_manage_preventive'] = can_manage_preventive
        ctx['can_execute_preventive'] = can_execute_preventive
        ctx['can_validate_preventive'] = can_validate_preventive
        ctx['can_complete_preventive'] = can_complete_preventive
        ctx['show_preventive_files'] = not (
            profile and profile.is_maintenance())
        ctx['statut_form'] = None if profile and profile.is_maintenance() else PreventiveStatutForm(
            preventive=preventive,
            allowed_statuses=allowed_statuses,
            status_labels=status_labels,
        )
        return ctx


class PreventiveCreateView(AdminRequiredMixin, CreateView):
    model = MaintenancePreventive
    form_class = MaintenancePreventiveForm
    template_name = 'maintenance/preventive_form.html'
    object: MaintenancePreventive

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


class PreventiveUpdateView(AdminRequiredMixin, UpdateView):
    model = MaintenancePreventive
    form_class = MaintenancePreventiveForm
    template_name = 'maintenance/preventive_form.html'
    object: MaintenancePreventive

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('preventive_detail', kwargs={'pk': self.object.pk})


@login_required
@require_POST
def preventive_changer_statut(request, pk):
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        raise PermissionDenied

    allowed_statuses = None
    if profile.is_maintenance():
        if not _maintenance_peut_valider_preventive(
            request.user, preventive
        ) or request.POST.get('nouveau_statut') != MaintenancePreventive.STATUT_EFFECTUEE:
            raise PermissionDenied
        allowed_statuses = {MaintenancePreventive.STATUT_EFFECTUEE}
    elif profile.is_silo():
        if preventive.affecte_a != request.user:
            raise PermissionDenied
        allowed_statuses = {
            MaintenancePreventive.STATUT_PRISE_EN_COMPTE,
            MaintenancePreventive.STATUT_EN_ATTENTE,
            MaintenancePreventive.STATUT_EFFECTUEE,
        }

    if request.method == 'POST':
        if (
            request.POST.get(
                'nouveau_statut') == MaintenancePreventive.STATUT_ARCHIVEE
            and not profile.is_admin()
        ):
            raise PermissionDenied
        form = PreventiveStatutForm(
            request.POST,
            preventive=preventive,
            allowed_statuses=allowed_statuses,
        )
        if form.is_valid():
            try:
                retour = form.cleaned_data.get('retour_intervention', '')
                preventive.changer_statut(
                    form.cleaned_data['nouveau_statut'],
                    request.user,
                    retour,
                )
                if (
                    profile.is_silo()
                    and form.cleaned_data['nouveau_statut'] == MaintenancePreventive.STATUT_EN_ATTENTE
                ):
                    notifier_admin_preventive_en_attente(
                        preventive,
                        request.user,
                        retour,
                    )
                if retour:
                    preventive.retour_intervention = retour
                    preventive.save(update_fields=['retour_intervention'])
                messages.success(request, 'Statut mis à jour.')
            except ValueError as e:
                messages.error(request, str(e))
    return redirect('preventive_detail', pk=pk)


@login_required
@require_POST
def preventive_envoyer(request, pk):
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied
    preventive.changer_statut(
        MaintenancePreventive.Statut.ENVOYEE, request.user, '')
    return redirect('preventive_detail', pk=pk)


@login_required
@require_POST
def preventive_recevoir(request, pk):
    preventive = get_object_or_404(
        MaintenancePreventive,
        pk=pk,
        site__in=get_sites_utilisateur(request.user),
    )
    if request.user != preventive.affecte_a:
        raise PermissionDenied
    preventive.changer_statut(
        MaintenancePreventive.Statut.RECUE, request.user, '')
    return redirect('preventive_detail', pk=pk)


@login_required
@require_POST
def preventive_demarrer(request, pk):
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)
    if request.user != preventive.affecte_a:
        raise PermissionDenied
    preventive.changer_statut(
        MaintenancePreventive.Statut.EN_COURS, request.user, '')
    return redirect('preventive_detail', pk=pk)


@login_required
def preventive_terminer(request, pk):
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)
    if request.user != preventive.affecte_a:
        raise PermissionDenied
    if request.method == 'POST':
        data = request.POST.copy()
        if 'retour' in data and 'retour_intervention' not in data:
            data['retour_intervention'] = data['retour']
        form = PreventiveTerminerForm(
            data,
            request.FILES,
            instance=preventive,
        )
        if form.is_valid():
            retour = form.cleaned_data['retour_intervention']
            preventive.retour_intervention = retour
            preventive.save(update_fields=['retour_intervention'])
            for fichier in form.cleaned_data['medias']:
                PreventiveMedia.objects.create(
                    preventive=preventive,
                    fichier=fichier,
                    nom_original=fichier.name,
                    ajoute_par=request.user,
                )
            preventive.changer_statut(
                MaintenancePreventive.Statut.A_VALIDER, request.user, retour)
            messages.success(
                request, 'Tâche terminée et envoyée pour validation.')
            return redirect('preventive_detail', pk=pk)
    else:
        form = PreventiveTerminerForm(instance=preventive)
    return render(request, 'maintenance/preventive_terminer.html', {
        'form': form,
        'preventive': preventive,
    })


@login_required
def preventive_media_telecharger(request, pk):
    media = get_object_or_404(
        PreventiveMedia.objects.select_related('preventive__site'),
        pk=pk,
    )
    profile = Profile.objects.filter(user=request.user).first()
    if not profile:
        raise PermissionDenied
    if profile.is_silo():
        site_accessible = get_sites_utilisateur(request.user).filter(
            pk=media.preventive.site_id,
        ).exists()
        if (
            not site_accessible
            or media.preventive.affecte_a_id != request.user.id
            or media.preventive.statut == MaintenancePreventive.Statut.ARCHIVEE
        ):
            raise PermissionDenied
    elif not profile.is_admin():
        raise PermissionDenied

    media.fichier.open('rb')
    return FileResponse(
        media.fichier,
        as_attachment=True,
        filename=media.nom_telechargement,
    )


@login_required
def preventive_valider(request, pk):
    preventive = get_object_or_404(MaintenancePreventive, pk=pk)
    profile = Profile.objects.filter(user=request.user).first()
    peut_valider = bool(
        profile and (
            profile.is_admin() or (
                profile.is_maintenance()
                and _maintenance_peut_valider_preventive(
                    request.user, preventive)
            )
        )
    )
    if not peut_valider:
        raise PermissionDenied
    if request.method == 'POST':
        form = PreventiveValiderForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            commentaire = form.cleaned_data.get('commentaire', '')
            nouveau_statut = (
                MaintenancePreventive.Statut.REJETEE
                if decision == 'rejeter'
                else MaintenancePreventive.Statut.VALIDEE
            )
            preventive.changer_statut(
                nouveau_statut, request.user, commentaire)
            if decision == 'valider' and profile.is_admin():
                preventive.changer_statut(
                    MaintenancePreventive.Statut.ARCHIVEE,
                    request.user,
                    'Archivage automatique après validation administrative.',
                )
            messages.success(request, 'Décision enregistrée.')
            return redirect('preventive_detail', pk=pk)
    else:
        form = PreventiveValiderForm()
    return render(request, 'maintenance/preventive_valider.html', {
        'form': form,
        'preventive': preventive,
    })


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
            Q(panne__site__in=sites) | Q(
                preventive__site__in=sites) | Q(
                preventive__equipement__site__in=sites)
        ).distinct().select_related('panne__equipement', 'preventive__equipement')

        statut = self.request.GET.get('statut')
        type_f = self.request.GET.get('type')
        q = self.request.GET.get('q')
        site_id = self.request.GET.get('site')
        start_raw = self.request.GET.get('start_date')
        end_raw = self.request.GET.get('end_date')

        if statut:
            qs = qs.filter(statut=statut)
        if type_f:
            qs = qs.filter(type_facture=type_f)
        if q:
            qs = qs.filter(Q(numero__icontains=q) |
                           Q(fournisseur__icontains=q))
        if site_id:
            qs = qs.filter(
                Q(panne__site_id=site_id)
                | Q(preventive__site_id=site_id)
                | Q(preventive__equipement__site_id=site_id)
            )
        try:
            start_date = date.fromisoformat(start_raw) if start_raw else None
        except ValueError:
            start_date = None
        try:
            end_date = date.fromisoformat(end_raw) if end_raw else None
        except ValueError:
            end_date = None
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
        if start_date:
            qs = qs.filter(date_facture__gte=start_date)
        if end_date:
            qs = qs.filter(date_facture__lte=end_date)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['statuts'] = Facture.STATUTS
        ctx['types'] = Facture.TYPES
        ctx['current_statut'] = self.request.GET.get('statut', '')
        ctx['current_type'] = self.request.GET.get('type', '')
        ctx['current_q'] = self.request.GET.get('q', '')
        ctx['sites'] = get_sites_utilisateur(self.request.user)
        ctx['current_site'] = self.request.GET.get('site', '')
        ctx['current_start_date'] = self.request.GET.get('start_date', '')
        ctx['current_end_date'] = self.request.GET.get('end_date', '')
        filters = self.request.GET.copy()
        filters.pop('page', None)
        ctx['filter_query'] = filters.urlencode()
        return ctx


class FactureDetailView(AdminRequiredMixin, DetailView):
    model = Facture
    template_name = 'maintenance/facture_detail.html'
    context_object_name = 'facture'


@login_required
def facture_telecharger(request, pk):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        raise PermissionDenied
    if not profile.is_admin():
        raise PermissionDenied
    facture = get_object_or_404(Facture, pk=pk)
    if not facture.fichier:
        raise PermissionDenied
    facture.fichier.open('rb')
    return FileResponse(facture.fichier, as_attachment=True)


@login_required
def facture_media_prive(request, chemin):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        raise PermissionDenied
    if not profile.is_admin():
        raise PermissionDenied
    facture = get_object_or_404(Facture, fichier=f'factures/{chemin}')
    facture.fichier.open('rb')
    return FileResponse(facture.fichier, as_attachment=True)


class FactureCreateView(AdminRequiredMixin, CreateView):
    model = Facture
    form_class = FactureForm
    template_name = 'maintenance/facture_form.html'
    object: Facture

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        sites = get_sites_utilisateur(self.request.user)
        panne_id = self.request.GET.get('panne')
        preventive_id = self.request.GET.get('preventive')
        kwargs['panne'] = (
            get_object_or_404(Panne, pk=panne_id, site__in=sites)
            if panne_id else None
        )
        kwargs['preventive'] = (
            get_object_or_404(
                MaintenancePreventive.objects.filter(
                    Q(site__in=sites) | Q(equipement__site__in=sites)
                ).distinct(),
                pk=preventive_id,
            ) if preventive_id else None
        )
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form")
        context["panne"] = getattr(form, "panne_imposee", None)
        context["preventive"] = getattr(form, "preventive_imposee", None)
        return context

    def get_success_url(self):
        return reverse('facture_detail', kwargs={'pk': self.object.pk})


class FactureUpdateView(AdminRequiredMixin, UpdateView):
    model = Facture
    form_class = FactureForm
    template_name = 'maintenance/facture_form.html'
    object: Facture

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('facture_detail', kwargs={'pk': self.object.pk})


class FactureDeleteView(AdminRequiredMixin, DeleteView):
    model = Facture
    template_name = 'maintenance/confirm_delete.html'
    success_url = reverse_lazy('facture_list')

    def form_valid(self, form):
        facture = self.get_object()
        assert isinstance(facture, Facture)
        facture.fichier.delete(save=False)
        facture.delete()
        messages.success(self.request, 'Facture supprimée.')
        return redirect(self.get_success_url())


class FactureFileDeleteView(AdminRequiredMixin, DetailView):
    model = Facture
    template_name = 'maintenance/confirm_file_delete.html'
    context_object_name = 'facture'

    def post(self, request, *args, **kwargs):
        facture = self.get_object()
        assert isinstance(facture, Facture)
        facture.fichier.delete(save=False)
        facture.fichier = None  # type: ignore[assignment]
        facture.save(update_fields=['fichier'])
        messages.success(request, 'Fichier de facture supprimé.')
        return redirect('facture_detail', pk=facture.pk)


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────

@login_required
def notifications(request):
    notifications_utilisateur = request.user.notifications.order_by(
        '-creee_le'
    )
    return render(
        request,
        'maintenance/notification_liste.html',
        {
            'notifications': notifications_utilisateur,
            'non_lues': notifications_utilisateur.filter(lue=False).count(),
        },
    )


@login_required
@require_POST
def marquer_notif_lue(request, pk):
    notif = get_object_or_404(Notification, pk=pk, utilisateur=request.user)
    notif.lue = True
    notif.save(update_fields=['lue'])
    if notif.lien:
        return redirect(notif.lien)
    return redirect('notification_liste')


@login_required
@require_POST
def marquer_toutes_lues(request):
    request.user.notifications.filter(lue=False).update(lue=True)
    messages.success(
        request, 'Toutes les notifications ont été marquées comme lues.')
    return redirect('notification_liste')


# ─────────────────────────────────────────────
# UTILISATEURS (admin seulement)
# ─────────────────────────────────────────────

class UtilisateurListView(AdminRequiredMixin, ListView):
    template_name = 'maintenance/utilisateur_list.html'
    context_object_name = 'utilisateurs'

    def get_queryset(self):
        return User.objects.select_related('profile').order_by('username')


class UtilisateurCreateView(AdminRequiredMixin, CreateView):
    form_class = UtilisateurCreateForm
    template_name = 'maintenance/utilisateur_form.html'
    success_url = reverse_lazy('utilisateur_list')

    def form_valid(self, form):
        messages.success(self.request, 'Utilisateur créé.')
        return super().form_valid(form)


class UtilisateurUpdateView(AdminRequiredMixin, UpdateView):
    model = User
    form_class = UtilisateurUpdateForm
    template_name = 'maintenance/utilisateur_form.html'
    success_url = reverse_lazy('utilisateur_list')

    def form_valid(self, form):
        messages.success(self.request, 'Utilisateur mis à jour.')
        return super().form_valid(form)


class UtilisateurDeleteView(AdminRequiredMixin, DeleteView):
    model = User
    template_name = 'maintenance/confirm_delete.html'
    success_url = reverse_lazy('utilisateur_list')

    def _suppression_interdite(self, utilisateur):
        if utilisateur == self.request.user:
            return "Vous ne pouvez pas supprimer votre propre compte."
        if (
            hasattr(utilisateur, 'profile')
            and utilisateur.profile.is_admin()
            and not Profile.objects.filter(
                role=Profile.Role.ADMIN,
                user__is_active=True,
            ).exclude(user=utilisateur).exists()
        ):
            return "Le dernier administrateur actif ne peut pas être supprimé."
        return None

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        erreur = self._suppression_interdite(self.object)
        if erreur:
            messages.error(request, erreur)
            return redirect(self.success_url)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        erreur = self._suppression_interdite(self.object)
        if erreur:
            messages.error(self.request, erreur)
            return redirect(self.success_url)
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                "Cet utilisateur ne peut pas être supprimé car il est lié "
                "à un historique de maintenance. Désactivez plutôt son compte.",
            )
            return redirect(self.success_url)
        messages.success(self.request, 'Utilisateur supprimé.')
        return response


@login_required
@require_POST
def utilisateur_changer_activation(request, pk):
    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.is_admin():
        raise PermissionDenied("Accès réservé à l'administrateur.")

    utilisateur = get_object_or_404(
        User.objects.select_related('profile'), pk=pk)
    actif_demande = request.POST.get('actif')
    if actif_demande not in {'0', '1'}:
        return HttpResponse("État de compte invalide.", status=400)
    rendre_actif = actif_demande == '1'

    if not rendre_actif and utilisateur == request.user:
        messages.error(
            request, "Vous ne pouvez pas désactiver votre propre compte.")
        return redirect('utilisateur_list')

    if (
        not rendre_actif
        and hasattr(utilisateur, 'profile')
        and utilisateur.profile.is_admin()
        and not Profile.objects.filter(
            role=Profile.Role.ADMIN,
            user__is_active=True,
        ).exclude(user=utilisateur).exists()
    ):
        messages.error(
            request,
            "Le dernier administrateur actif ne peut pas être désactivé.",
        )
        return redirect('utilisateur_list')

    utilisateur.is_active = rendre_actif
    utilisateur.save(update_fields=['is_active'])
    messages.success(
        request,
        "Compte réactivé." if rendre_actif else "Compte désactivé.",
    )
    return redirect('utilisateur_list')


# ─────────────────────────────────────────────
# PROFIL
# ─────────────────────────────────────────────

@login_required
def mon_profil(request):
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        raise PermissionDenied

    if request.method == 'POST':
        form = ProfileUpdateForm(
            request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save(user=request.user)
            messages.success(request, 'Profil mis à jour.')
            return redirect('mon_profil')
    else:
        form = ProfileUpdateForm(instance=profile, user=request.user)

    return render(request, 'maintenance/mon_profil.html', {'form': form, 'profile': profile})
