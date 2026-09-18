from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0015_cellulegrain_capacite_tonnes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cellulegrain",
            name="capacite_m3",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                editable=False,
                max_digits=10,
                verbose_name="volume utile (m³)",
            ),
        ),
    ]
