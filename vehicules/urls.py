from django.urls import path

from . import views

app_name = "vehicules"

urlpatterns = [
    path("", views.VehiculeListView.as_view(), name="liste"),
    path("ajouter/", views.VehiculeCreateView.as_view(), name="ajouter"),
    path("<int:pk>/", views.VehiculeDetailView.as_view(), name="detail"),
    path("<int:pk>/modifier/", views.VehiculeUpdateView.as_view(), name="modifier"),
    path("<int:pk>/supprimer/", views.VehiculeDeleteView.as_view(), name="supprimer"),
    path("<int:pk>/photo/", views.VehiculePhotoView.as_view(), name="photo"),
    path("<int:pk>/vgp/", views.VehiculeRapportVgpView.as_view(), name="rapport_vgp"),
    path("<int:vehicule_pk>/entretiens/ajouter/",
         views.EntretienCreateView.as_view(), name="entretien_ajouter"),
    path("<int:vehicule_pk>/carburant/ajouter/",
         views.ReleveCarburantCreateView.as_view(), name="carburant_ajouter"),
    path("<int:vehicule_pk>/immobilisations/ajouter/",
         views.ImmobilisationCreateView.as_view(), name="immobilisation_ajouter"),
    path("immobilisations/<int:pk>/cloturer/",
         views.ImmobilisationClotureView.as_view(), name="immobilisation_cloturer"),
    path("<int:vehicule_pk>/documents-reglementaires/ajouter/",
         views.DocumentReglementaireCreateView.as_view(), name="document_reglementaire_ajouter"),
    path("documents-reglementaires/<int:pk>/telecharger/",
         views.DocumentReglementaireDownloadView.as_view(), name="document_reglementaire_telecharger"),
    path("entretiens/<int:pk>/supprimer/",
         views.EntretienDeleteView.as_view(), name="entretien_supprimer"),
    path("entretiens/<int:pk>/facture/",
         views.EntretienFactureView.as_view(), name="entretien_facture"),
]
