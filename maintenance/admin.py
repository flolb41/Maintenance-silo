from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    Site, Profile, Equipement, Panne, HistoriquePanne, PanneMedia,
    MaintenancePreventive, HistoriquePreventive, PreventiveMedia,
    Facture, Notification
)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profil'


class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ('nom', 'adresse', 'created_at')
    search_fields = ('nom', 'adresse')


@admin.register(Equipement)
class EquipementAdmin(admin.ModelAdmin):
    list_display = ('nom', 'site', 'categorie', 'reference', 'actif')
    list_filter = ('site', 'categorie', 'actif')
    search_fields = ('nom', 'reference')


class HistoriquePanneInline(admin.TabularInline):
    model = HistoriquePanne
    extra = 0
    readonly_fields = ('ancien_statut', 'nouveau_statut', 'modifie_par', 'commentaire', 'date')


class PanneMediaInline(admin.TabularInline):
    model = PanneMedia
    extra = 0


@admin.register(Panne)
class PanneAdmin(admin.ModelAdmin):
    list_display = ('titre', 'equipement', 'priorite', 'statut', 'signale_par', 'date_signalement')
    list_filter = ('statut', 'priorite', 'equipement__site')
    search_fields = ('titre', 'description')
    inlines = [PanneMediaInline, HistoriquePanneInline]
    readonly_fields = ('created_at', 'updated_at')


class HistoriquePreventiveInline(admin.TabularInline):
    model = HistoriquePreventive
    extra = 0
    readonly_fields = ('ancien_statut', 'nouveau_statut', 'modifie_par', 'commentaire', 'date')


@admin.register(MaintenancePreventive)
class MaintenancePreventiveAdmin(admin.ModelAdmin):
    list_display = ('titre', 'equipement', 'periodicite', 'date_echeance', 'statut')
    list_filter = ('statut', 'periodicite', 'equipement__site')
    search_fields = ('titre', 'description')
    inlines = [HistoriquePreventiveInline]
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = ('numero', 'fournisseur', 'type_facture', 'statut', 'montant_ttc', 'date_facture')
    list_filter = ('statut', 'type_facture')
    search_fields = ('numero', 'fournisseur')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('titre', 'destinataire', 'type_notif', 'lue', 'created_at')
    list_filter = ('type_notif', 'lue')
    search_fields = ('titre', 'message')
