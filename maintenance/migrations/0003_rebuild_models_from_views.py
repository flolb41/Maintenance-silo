import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("maintenance", "0002_historiquepanne_historiquepreventive"),
    ]

    operations = [
        migrations.RenameField("panne", "declarant", "signale_par"),
        migrations.RenameField("panne", "agent_assigne", "affecte_a"),
        migrations.RenameField("panne", "creee_le", "date_signalement"),
        migrations.RenameField("panne", "modifiee_le", "updated_at"),
        migrations.AlterField(
            model_name="panne",
            name="signale_par",
            field=models.ForeignKey(
                db_column="declarant_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pannes_declarees",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="panne",
            name="affecte_a",
            field=models.ForeignKey(
                blank=True,
                db_column="agent_assigne_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pannes_assignees",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="panne",
            name="date_signalement",
            field=models.DateTimeField(
                auto_now_add=True, db_column="creee_le"),
        ),
        migrations.AlterField(
            model_name="panne",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_column="modifiee_le"),
        ),
        migrations.AddField(
            model_name="panne",
            name="created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="panne",
            name="date_resolution",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name="panne", options={"ordering": ["-date_signalement"]}
        ),
        migrations.RenameField("maintenancepreventive",
                               "createur", "created_by"),
        migrations.RenameField("maintenancepreventive",
                               "destinataire", "affecte_a"),
        migrations.RenameField("maintenancepreventive",
                               "instructions", "description"),
        migrations.RenameField("maintenancepreventive",
                               "echeance", "date_echeance"),
        migrations.RenameField("maintenancepreventive",
                               "retour", "retour_intervention"),
        migrations.RenameField("maintenancepreventive",
                               "creee_le", "created_at"),
        migrations.RenameField("maintenancepreventive",
                               "modifiee_le", "updated_at"),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="created_by",
            field=models.ForeignKey(
                db_column="createur_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="maintenances_creees",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="affecte_a",
            field=models.ForeignKey(
                db_column="destinataire_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="maintenances_recues",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="description",
            field=models.TextField(db_column="instructions"),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="date_echeance",
            field=models.DateTimeField(db_column="echeance"),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="retour_intervention",
            field=models.TextField(blank=True, db_column="retour"),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, db_column="creee_le"),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_column="modifiee_le"),
        ),
        migrations.AlterField(
            model_name="maintenancepreventive",
            name="statut",
            field=models.CharField(
                choices=[
                    ("brouillon", "Brouillon"),
                    ("envoyee", "Envoyée"),
                    ("recue", "Reçue"),
                    ("en_cours", "En cours"),
                    ("a_valider", "À valider"),
                    ("validee", "Validée"),
                    ("rejetee", "Rejetée"),
                    ("en_retard", "En retard"),
                    ("effectuee", "Effectuée"),
                    ("prise_en_compte", "Prise en compte"),
                    ("en_attente", "En attente"),
                    ("archivee", "Archivée"),
                    ("annulee", "Annulée"),
                    ("planifiee", "Planifiée"),
                ],
                default="brouillon",
                max_length=30,
            ),
        ),
        migrations.AlterModelOptions(
            name="maintenancepreventive", options={"ordering": ["-created_at"]}
        ),
        migrations.AlterField(
            model_name="facture",
            name="panne",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="factures",
                to="maintenance.panne",
            ),
        ),
        migrations.AddField(
            model_name="facture",
            name="preventive",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="factures",
                to="maintenance.maintenancepreventive",
            ),
        ),
        migrations.AddField(
            model_name="facture",
            name="type_facture",
            field=models.CharField(
                choices=[
                    ("autre", "Autre"),
                    ("maintenance", "Maintenance"),
                    ("revision", "Révision"),
                ],
                default="autre",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="facture",
            name="statut",
            field=models.CharField(
                choices=[
                    ("brouillon", "Brouillon"),
                    ("valide", "Validée"),
                    ("rejete", "Rejetée"),
                ],
                default="brouillon",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="facture",
            name="statut_detection",
            field=models.CharField(
                choices=[("ok", "Complète"), ("incomplete", "Incomplète")],
                default="incomplete",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="facture",
            name="taux_tva",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="facture",
            name="montant_tva",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="facture",
            name="date_facture",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="facture",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="facture",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="factures_creees",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
