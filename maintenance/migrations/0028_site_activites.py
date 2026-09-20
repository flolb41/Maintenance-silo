from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0027_piece_detachee_mouvement"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="activite_silos",
            field=models.BooleanField(
                default=True, verbose_name="Activité silos"),
        ),
        migrations.AddField(
            model_name="site",
            name="activite_vehicules",
            field=models.BooleanField(
                default=True,
                verbose_name="Activité véhicules",
            ),
        ),
    ]
