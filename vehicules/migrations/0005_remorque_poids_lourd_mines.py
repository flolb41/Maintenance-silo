from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicules", "0004_vehicule_immatriculation_optional"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicule",
            name="categorie",
            field=models.CharField(
                choices=[
                    ("pl", "Poids lourd"),
                    ("em", "Engin de manutention"),
                    ("rm", "Remorque poids lourd"),
                ],
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name="vehicule",
            name="date_mines",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Échéance passage aux mines",
            ),
        ),
    ]
