from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import maintenance.storage


class Migration(migrations.Migration):
    dependencies = [("vehicules", "0007_vehicule_periodicite_revision")]

    operations = [
        migrations.CreateModel(
            name="ReleveCarburantVehicule",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("produit", models.CharField(choices=[
                 ("carburant", "Carburant"), ("adblue", "AdBlue")], max_length=12)),
                ("date_releve", models.DateField()),
                ("quantite_litres", models.DecimalField(
                    decimal_places=2, max_digits=8)),
                ("kilometrage", models.PositiveIntegerField()),
                ("cout", models.DecimalField(blank=True,
                 decimal_places=2, max_digits=10, null=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                 related_name="releves_carburant_crees", to=settings.AUTH_USER_MODEL)),
                ("vehicule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="releves_carburant", to="vehicules.vehicule")),
            ], options={"ordering": ["-date_releve", "-cree_le"]},
        ),
        migrations.CreateModel(
            name="ImmobilisationVehicule",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("nature", models.CharField(choices=[
                 ("en_entretien", "En entretien"), ("hors_service", "Hors service")], max_length=20)),
                ("debut", models.DateField()), ("fin",
                                                models.DateField(blank=True, null=True)),
                ("motif", models.TextField()), ("cree_le",
                                                models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                 related_name="immobilisations_vehicules_crees", to=settings.AUTH_USER_MODEL)),
                ("vehicule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="immobilisations", to="vehicules.vehicule")),
            ], options={"ordering": ["-debut", "-cree_le"]},
        ),
        migrations.CreateModel(
            name="DocumentReglementaireVehicule",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("type_document", models.CharField(choices=[("assurance", "Assurance"), (
                    "controle_technique", "Contrôle technique"), ("mines", "Passage aux mines")], max_length=20)),
                ("fichier", models.FileField(storage=maintenance.storage.private_invoice_storage,
                 upload_to="vehicules/reglementaire/%Y/%m/")),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                 related_name="documents_reglementaires_vehicules_crees", to=settings.AUTH_USER_MODEL)),
                ("vehicule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="documents_reglementaires", to="vehicules.vehicule")),
            ], options={"ordering": ["type_document", "-cree_le"]},
        ),
        migrations.AddConstraint(model_name="immobilisationvehicule", constraint=models.UniqueConstraint(
            condition=models.Q(("fin__isnull", True)), fields=("vehicule",), name="unique_immobilisation_ouverte_vehicule")),
    ]
