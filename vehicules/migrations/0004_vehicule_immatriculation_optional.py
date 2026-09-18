from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("vehicules", "0003_vehicule_engin_vgp"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicule",
            name="immatriculation",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddConstraint(
            model_name="vehicule",
            constraint=models.UniqueConstraint(
                condition=~Q(immatriculation=""),
                fields=("immatriculation",),
                name="vehicule_immatriculation_non_vide_unique",
            ),
        ),
    ]
