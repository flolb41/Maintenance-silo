from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicules", "0002_entretien_facture_private_storage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicule",
            name="categorie",
            field=models.CharField(
                choices=[
                    ("pl", "Poids lourd"),
                    ("em", "Engin de manutention"),
                ],
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name="vehicule",
            name="date_vgp",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Échéance VGP",
            ),
        ),
        migrations.AddField(
            model_name="vehicule",
            name="organisme_vgp",
            field=models.CharField(
                blank=True,
                default="DEKRA",
                max_length=100,
                verbose_name="Organisme VGP",
            ),
        ),
    ]
