from django.db import migrations
from django.utils import timezone


def archive_admin_validated_preventives(apps, schema_editor):
    MaintenancePreventive = apps.get_model(
        "maintenance", "MaintenancePreventive"
    )
    HistoriquePreventive = apps.get_model(
        "maintenance", "HistoriquePreventive"
    )

    preventives = MaintenancePreventive.objects.filter(statut="validee")
    for preventive in preventives.iterator():
        validation = HistoriquePreventive.objects.filter(
            preventive_id=preventive.pk,
            nouveau_statut="validee",
            modifie_par__profile__role="admin",
        ).order_by("-creee_le", "-pk").first()
        if validation is None:
            continue

        MaintenancePreventive.objects.filter(pk=preventive.pk).update(
            statut="archivee",
            updated_at=timezone.now(),
        )
        HistoriquePreventive.objects.create(
            preventive_id=preventive.pk,
            ancien_statut="validee",
            nouveau_statut="archivee",
            modifie_par_id=validation.modifie_par_id,
            commentaire="Archivage des validations administratives existantes.",
        )


def restore_admin_validated_preventives(apps, schema_editor):
    MaintenancePreventive = apps.get_model(
        "maintenance", "MaintenancePreventive"
    )
    HistoriquePreventive = apps.get_model(
        "maintenance", "HistoriquePreventive"
    )
    migration_comment = "Archivage des validations administratives existantes."

    archived_histories = HistoriquePreventive.objects.filter(
        ancien_statut="validee",
        nouveau_statut="archivee",
        commentaire=migration_comment,
    )
    preventive_ids = list(
        archived_histories.values_list("preventive_id", flat=True)
    )
    MaintenancePreventive.objects.filter(
        pk__in=preventive_ids,
        statut="archivee",
    ).update(statut="validee", updated_at=timezone.now())
    archived_histories.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0011_facture_private_storage"),
    ]

    operations = [
        migrations.RunPython(
            archive_admin_validated_preventives,
            restore_admin_validated_preventives,
        ),
    ]
