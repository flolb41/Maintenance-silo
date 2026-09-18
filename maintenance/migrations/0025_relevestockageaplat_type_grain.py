from django.db import migrations, models
import django.db.models.deletion


def renseigner_type_grain_des_releves(apps, schema_editor):
    ReleveStockageAPlat = apps.get_model("maintenance", "ReleveStockageAPlat")
    for releve in ReleveStockageAPlat.objects.select_related("stockage"):
        releve.type_grain_id = releve.stockage.type_grain_id
        releve.save(update_fields=["type_grain"])


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0024_stockage_a_plat"),
    ]

    operations = [
        migrations.AddField(
            model_name="relevestockageaplat",
            name="type_grain",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="releves_stockages_a_plat",
                to="maintenance.typegrain",
                verbose_name="type de grain",
            ),
        ),
        migrations.RunPython(
            renseigner_type_grain_des_releves,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="relevestockageaplat",
            name="type_grain",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="releves_stockages_a_plat",
                to="maintenance.typegrain",
                verbose_name="type de grain",
            ),
        ),
    ]
