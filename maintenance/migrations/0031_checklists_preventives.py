from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0030_piece_panne")]

    operations = [
        migrations.CreateModel(
            name="ChecklistModele",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=150, unique=True)),
                ("description", models.TextField(blank=True)),
                ("actif", models.BooleanField(default=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["nom"]},
        ),
        migrations.CreateModel(
            name="ChecklistModeleElement",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("ordre", models.PositiveSmallIntegerField(default=1)),
                ("libelle", models.CharField(max_length=255)),
                ("obligatoire", models.BooleanField(default=True)),
                ("modele", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="elements", to="maintenance.checklistmodele")),
            ],
            options={"ordering": ["ordre", "pk"]},
        ),
        migrations.CreateModel(
            name="ChecklistPreventive",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=150)),
                ("affectee_le", models.DateTimeField(auto_now_add=True)),
                ("modele_source", models.ForeignKey(blank=True, null=True,
                 on_delete=django.db.models.deletion.SET_NULL, to="maintenance.checklistmodele")),
                ("preventive", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                 related_name="checklist", to="maintenance.maintenancepreventive")),
            ],
        ),
        migrations.CreateModel(
            name="ChecklistPreventiveElement",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("ordre", models.PositiveSmallIntegerField(default=1)),
                ("libelle", models.CharField(max_length=255)),
                ("obligatoire", models.BooleanField(default=True)),
                ("coche", models.BooleanField(default=False)),
                ("coche_le", models.DateTimeField(blank=True, null=True)),
                ("checklist", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="elements", to="maintenance.checklistpreventive")),
                ("coche_par", models.ForeignKey(blank=True, null=True,
                 on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["ordre", "pk"]},
        ),
    ]
