from decimal import Decimal

from django.db import migrations, models


def renseigner_capacites_tonnes(apps, schema_editor):
    CelluleGrain = apps.get_model("maintenance", "CelluleGrain")
    for cellule in CelluleGrain.objects.all().iterator():
        cellule.capacite_tonnes = (
            cellule.capacite_m3 * Decimal("0.75")
        ).quantize(Decimal("0.01"))
        cellule.save(update_fields=["capacite_tonnes"])


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0014_silo_cellules"),
    ]

    operations = [
        migrations.AddField(
            model_name="cellulegrain",
            name="capacite_tonnes",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                editable=False,
                max_digits=10,
                verbose_name="capacité (t)",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(
            renseigner_capacites_tonnes,
            migrations.RunPython.noop,
        ),
    ]
