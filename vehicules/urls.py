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
    path("entretiens/<int:pk>/supprimer/",
         views.EntretienDeleteView.as_view(), name="entretien_supprimer"),
    path("entretiens/<int:pk>/facture/",
         views.EntretienFactureView.as_view(), name="entretien_facture"),
]
