from django.db import migrations, models
import maintenance.storage


class Migration(migrations.Migration):
    dependencies = [
        ("vehicules", "0005_remorque_poids_lourd_mines"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicule",
            name="rapport_vgp",
            field=models.FileField(
                blank=True,
                storage=maintenance.storage.private_invoice_storage,
                upload_to="vehicules/vgp/%Y/%m/",
                verbose_name="Rapport VGP (PDF)",
            ),
        ),
    ]
