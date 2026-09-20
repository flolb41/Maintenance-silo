from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicules", "0006_vehicule_rapport_vgp"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicule",
            name="periodicite_revision_km",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name="Périodicité révision (km)",
            ),
        ),
        migrations.AddField(
            model_name="vehicule",
            name="periodicite_revision_mois",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="Périodicité révision (mois)",
            ),
        ),
    ]
