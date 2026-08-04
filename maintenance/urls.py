from django.urls import path

from . import views

urlpatterns = [
    # Dashboard
    path("dashboard/", views.dashboard, name="dashboard"),
    path("", views.dashboard, name="home"),

    # Pannes
    path("pannes/", views.panne_liste, name="panne_liste"),
    path("pannes/creer/", views.panne_creer, name="panne_creer"),
    path("pannes/<int:pk>/", views.panne_detail, name="panne_detail"),
    path("pannes/<int:pk>/affecter/", views.panne_affecter, name="panne_affecter"),
    path("pannes/<int:pk>/statut/", views.panne_changer_statut, name="panne_changer_statut"),
    path("pannes/<int:pk>/media/", views.panne_ajouter_media, name="panne_ajouter_media"),
    path("pannes/<int:pk>/facture/", views.panne_ajouter_facture, name="panne_ajouter_facture"),

    # Maintenances préventives
    path("preventives/", views.preventive_liste, name="preventive_liste"),
    path("preventives/creer/", views.preventive_creer, name="preventive_creer"),
    path("preventives/<int:pk>/", views.preventive_detail, name="preventive_detail"),
    path("preventives/<int:pk>/envoyer/", views.preventive_envoyer, name="preventive_envoyer"),
    path("preventives/<int:pk>/recevoir/", views.preventive_recevoir, name="preventive_recevoir"),
    path("preventives/<int:pk>/demarrer/", views.preventive_demarrer, name="preventive_demarrer"),
    path("preventives/<int:pk>/terminer/", views.preventive_terminer, name="preventive_terminer"),
    path("preventives/<int:pk>/valider/", views.preventive_valider, name="preventive_valider"),

    # Notifications
    path("notifications/", views.notification_liste, name="notification_liste"),
    path("notifications/<int:pk>/lue/", views.notification_marquer_lue, name="notification_marquer_lue"),
    path("notifications/tout-lire/", views.notification_tout_lire, name="notification_tout_lire"),
]
