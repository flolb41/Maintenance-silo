from django.contrib import admin

from .models import (
    CelluleGrain,
    ChecklistModele,
    ChecklistModeleElement,
    Equipement,
    Facture,
    MaintenancePreventive,
    Notification,
    Panne,
    PanneMedia,
    PreventiveMedia,
    Profile,
    ReleveStockageAPlat,
    Silo,
    Site,
    StockageAPlat,
    TypeGrain,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__username",)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif")
    list_filter = ("actif",)
    search_fields = ("nom", "adresse")
    filter_horizontal = ("utilisateurs",)


@admin.register(Silo)
class SiloAdmin(admin.ModelAdmin):
    list_display = ("nom", "site", "actif")
    list_filter = ("site", "actif")
    search_fields = ("nom", "site__nom", "description")


@admin.register(CelluleGrain)
class CelluleGrainAdmin(admin.ModelAdmin):
    list_display = ("nom", "marque", "silo", "site", "type_grain",
                    "forme", "capacite_tonnes", "actif")
    list_filter = ("site", "silo", "marque", "type_grain", "forme", "actif")
    search_fields = ("nom", "marque", "silo__nom", "site__nom")
    readonly_fields = ("site", "capacite_tonnes")


@admin.register(StockageAPlat)
class StockageAPlatAdmin(admin.ModelAdmin):
    list_display = ("nom", "site", "type_grain", "actif")
    list_filter = ("site", "type_grain", "actif")
    search_fields = ("nom", "site__nom")


@admin.register(ReleveStockageAPlat)
class ReleveStockageAPlatAdmin(admin.ModelAdmin):
    list_display = ("stockage", "tonnage", "releve_le", "releve_par")
    list_filter = ("stockage__site", "stockage__type_grain")
    search_fields = ("stockage__nom", "stockage__site__nom")


@admin.register(TypeGrain)
class TypeGrainAdmin(admin.ModelAdmin):
    list_display = ("nom", "poids_specifique_moyen", "actif")
    list_filter = ("actif",)
    search_fields = ("nom",)


class ChecklistModeleElementInline(admin.TabularInline):
    model = ChecklistModeleElement
    extra = 1


@admin.register(ChecklistModele)
class ChecklistModeleAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif", "cree_le")
    list_filter = ("actif",)
    search_fields = ("nom", "description")
    inlines = [ChecklistModeleElementInline]


@admin.register(Equipement)
class EquipementAdmin(admin.ModelAdmin):
    list_display = ("nom", "site", "reference", "actif")
    list_filter = ("site", "actif")
    search_fields = ("nom", "reference")


class PanneMediaInline(admin.TabularInline):
    model = PanneMedia
    extra = 0
    readonly_fields = ("cree_le",)


class FactureInline(admin.TabularInline):
    model = Facture
    extra = 0
    readonly_fields = ("creee_le",)


@admin.register(Panne)
class PanneAdmin(admin.ModelAdmin):
    list_display = ("titre", "site", "priorite", "statut",
                    "declarant", "agent_assigne", "creee_le")
    list_filter = ("site", "priorite", "statut")
    search_fields = ("titre", "description")
    readonly_fields = ("creee_le", "modifiee_le")
    inlines = [PanneMediaInline, FactureInline]


class PreventiveMediaInline(admin.TabularInline):
    model = PreventiveMedia
    extra = 0
    readonly_fields = ("cree_le",)


@admin.register(MaintenancePreventive)
class MaintenancePreventiveAdmin(admin.ModelAdmin):
    list_display = ("titre", "site", "statut", "createur",
                    "destinataire", "echeance")
    list_filter = ("site", "statut")
    search_fields = ("titre", "instructions")
    readonly_fields = ("creee_le", "modifiee_le")
    inlines = [PreventiveMediaInline]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("titre", "utilisateur", "type_notif", "lue", "creee_le")
    list_filter = ("lue", "type_notif")
    search_fields = ("titre", "message")
    readonly_fields = ("creee_le",)
