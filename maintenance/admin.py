from django.contrib import admin

from .models import (
    Equipement,
    Facture,
    MaintenancePreventive,
    Notification,
    Panne,
    PanneMedia,
    PreventiveMedia,
    Profile,
    Site,
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
    list_display = ("titre", "site", "priorite", "statut", "declarant", "agent_assigne", "creee_le")
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
    list_display = ("titre", "site", "statut", "createur", "destinataire", "echeance")
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
