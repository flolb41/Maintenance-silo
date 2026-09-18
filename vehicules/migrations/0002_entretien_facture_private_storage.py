import shutil
from filecmp import cmp
from pathlib import Path

import maintenance.storage
from django.conf import settings
from django.db import migrations, models


def _move_vehicle_invoices(apps, source_root, destination_root):
    EntretienVehicule = apps.get_model("vehicules", "EntretienVehicule")
    source_root = Path(source_root).resolve()
    destination_root = Path(destination_root).resolve()

    for entretien in EntretienVehicule.objects.exclude(facture="").iterator():
        relative_path = Path(entretien.facture.name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            continue

        source = source_root / relative_path
        destination = destination_root / relative_path
        if not source.is_file():
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
        if destination.is_file() and cmp(source, destination, shallow=False):
            source.unlink()


def move_vehicle_invoices_to_private_storage(apps, schema_editor):
    _move_vehicle_invoices(
        apps,
        settings.MEDIA_ROOT,
        settings.PRIVATE_INVOICE_ROOT,
    )


def restore_vehicle_invoices_to_media_storage(apps, schema_editor):
    _move_vehicle_invoices(
        apps,
        settings.PRIVATE_INVOICE_ROOT,
        settings.MEDIA_ROOT,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0011_facture_private_storage"),
        ("vehicules", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            move_vehicle_invoices_to_private_storage,
            restore_vehicle_invoices_to_media_storage,
        ),
        migrations.AlterField(
            model_name="entretienvehicule",
            name="facture",
            field=models.FileField(
                blank=True,
                storage=maintenance.storage.PrivateInvoiceStorage(),
                upload_to="vehicules/factures/%Y/%m/",
            ),
        ),
    ]
