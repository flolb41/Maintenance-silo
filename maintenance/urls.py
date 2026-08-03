from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('connexion/', views.connexion, name='connexion'),
    path('deconnexion/', views.deconnexion, name='deconnexion'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Sites
    path('sites/', views.SiteListView.as_view(), name='site_list'),
    path('sites/nouveau/', views.SiteCreateView.as_view(), name='site_create'),
    path('sites/<int:pk>/modifier/', views.SiteUpdateView.as_view(), name='site_update'),
    path('sites/<int:pk>/supprimer/', views.SiteDeleteView.as_view(), name='site_delete'),

    # Équipements
    path('equipements/', views.EquipementListView.as_view(), name='equipement_list'),
    path('equipements/nouveau/', views.EquipementCreateView.as_view(), name='equipement_create'),
    path('equipements/<int:pk>/modifier/', views.EquipementUpdateView.as_view(), name='equipement_update'),
    path('equipements/<int:pk>/supprimer/', views.EquipementDeleteView.as_view(), name='equipement_delete'),

    # Pannes
    path('pannes/', views.PanneListView.as_view(), name='panne_list'),
    path('pannes/nouvelle/', views.PanneCreateView.as_view(), name='panne_create'),
    path('pannes/<int:pk>/', views.PanneDetailView.as_view(), name='panne_detail'),
    path('pannes/<int:pk>/statut/', views.panne_changer_statut, name='panne_changer_statut'),
    path('pannes/<int:pk>/affecter/', views.panne_affecter, name='panne_affecter'),
    path('pannes/<int:pk>/media/', views.panne_ajouter_media, name='panne_ajouter_media'),

    # Maintenances préventives
    path('preventives/', views.PreventiveListView.as_view(), name='preventive_list'),
    path('preventives/nouvelle/', views.PreventiveCreateView.as_view(), name='preventive_create'),
    path('preventives/<int:pk>/', views.PreventiveDetailView.as_view(), name='preventive_detail'),
    path('preventives/<int:pk>/modifier/', views.PreventiveUpdateView.as_view(), name='preventive_update'),
    path('preventives/<int:pk>/statut/', views.preventive_changer_statut, name='preventive_changer_statut'),

    # Factures
    path('factures/', views.FactureListView.as_view(), name='facture_list'),
    path('factures/nouvelle/', views.FactureCreateView.as_view(), name='facture_create'),
    path('factures/<int:pk>/', views.FactureDetailView.as_view(), name='facture_detail'),
    path('factures/<int:pk>/modifier/', views.FactureUpdateView.as_view(), name='facture_update'),

    # Notifications
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/<int:pk>/lue/', views.marquer_notif_lue, name='notif_lue'),
    path('notifications/toutes-lues/', views.marquer_toutes_lues, name='notifs_toutes_lues'),

    # Utilisateurs
    path('utilisateurs/', views.UtilisateurListView.as_view(), name='utilisateur_list'),
    path('utilisateurs/nouveau/', views.UtilisateurCreateView.as_view(), name='utilisateur_create'),

    # Profil
    path('profil/', views.mon_profil, name='mon_profil'),
]
