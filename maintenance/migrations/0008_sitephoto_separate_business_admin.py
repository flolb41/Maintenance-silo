import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def retirer_acces_staff_aux_administrateurs_metier(apps, schema_editor):
    Profile = apps.get_model("maintenance", "Profile")
    User = apps.get_model("auth", "User")
    user_ids = Profile.objects.filter(
        role="admin").values_list("user_id", flat=True)
    User.objects.filter(
        pk__in=user_ids, is_superuser=False).update(is_staff=False)


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0007_alter_maintenancepreventive_statut"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SitePhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("fichier", models.ImageField(upload_to="sites/%Y/%m/")),
                ("nom_original", models.CharField(max_length=255)),
                ("creee_le", models.DateTimeField(auto_now_add=True)),
                ("ajoutee_par", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                 related_name="photos_sites_ajoutees", to=settings.AUTH_USER_MODEL)),
                ("site", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="photos", to="maintenance.site")),
            ],
            options={"ordering": ["-creee_le"]},
        ),
        migrations.RunPython(
            retirer_acces_staff_aux_administrateurs_metier,
            migrations.RunPython.noop,
        ),
    ]
