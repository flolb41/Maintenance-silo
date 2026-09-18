from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0025_relevestockageaplat_type_grain"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipement",
            name="equipement_parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="sous_equipements",
                to="maintenance.equipement",
                verbose_name="Équipement parent",
            ),
        ),
    ]
