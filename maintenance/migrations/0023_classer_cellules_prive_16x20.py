from decimal import Decimal

from django.db import migrations


def classer_cellules_prive_16x20(apps, schema_editor):
    CelluleGrain = apps.get_model("maintenance", "CelluleGrain")
    CelluleGrain.objects.filter(
        marque="",
        forme="ronde",
        diametre_m=Decimal("16.00"),
        hauteur_m=Decimal("20.00"),
    ).update(
        marque="Privé",
        capacite_tonnes=Decimal("2700.00"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0022_cellulegrain_marque"),
    ]

    operations = [
        migrations.RunPython(
            classer_cellules_prive_16x20,
            migrations.RunPython.noop,
        ),
    ]
