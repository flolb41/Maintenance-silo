from django.contrib import admin

from .models import (
    Equipement,
    Facture,
    MaintenancePreventive,
    Notification,
    Panne,
    PanneMedia,
    Profile,
    Site,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif")
    list_filter = ("actif",)
    search_fields = ("nom", "adresse")


@admin.register(Equipement)
class EquipementAdmin(admin.ModelAdmin):
    list_display = ("nom", "site", "reference", "actif")
    list_filter = ("site", "actif")
    search_fields = ("nom", "reference")


@admin.register(Panne)
class PanneAdmin(admin.ModelAdmin):
    list_display = (
        "titre",
        "site",
        "priorite",
        "statut",
        "declarant",
        "agent_assigne",
    )
    list_filter = ("site", "priorite", "statut")
    search_fields = ("titre", "description")


@admin.register(MaintenancePreventive)
class MaintenancePreventiveAdmin(admin.ModelAdmin):
    list_display = ("titre", "site", "statut", "echeance", "destinataire")
    list_filter = ("site", "statut")
    search_fields = ("titre", "instructions")


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = ("numero", "fournisseur", "panne", "montant_ttc", "validee")
    list_filter = ("validee",)
    search_fields = ("numero", "fournisseur")


admin.site.register(PanneMedia)
admin.site.register(Notification)
