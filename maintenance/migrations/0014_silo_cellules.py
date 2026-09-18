from django.db import migrations, models
import django.db.models.deletion


def rattacher_cellules_aux_silos(apps, schema_editor):
    Silo = apps.get_model("maintenance", "Silo")
    CelluleGrain = apps.get_model("maintenance", "CelluleGrain")

    for site_id in CelluleGrain.objects.values_list("site_id", flat=True).distinct():
        silo, _ = Silo.objects.get_or_create(
            site_id=site_id,
            nom="Silo principal",
            defaults={"actif": True},
        )
        CelluleGrain.objects.filter(site_id=site_id).update(silo_id=silo.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0013_typegrain_cellulegrain_relevecellule_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Silo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nom", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("actif", models.BooleanField(default=True)),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="silos",
                        to="maintenance.site",
                    ),
                ),
            ],
            options={
                "ordering": ["site__nom", "nom"],
            },
        ),
        migrations.RemoveConstraint(
            model_name="cellulegrain",
            name="unique_cellule_grain_par_site",
        ),
        migrations.AddField(
            model_name="cellulegrain",
            name="silo",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cellules",
                to="maintenance.silo",
            ),
        ),
        migrations.RunPython(
            rattacher_cellules_aux_silos,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="cellulegrain",
            name="silo",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cellules",
                to="maintenance.silo",
            ),
        ),
        migrations.AlterModelOptions(
            name="cellulegrain",
            options={"ordering": ["site__nom", "silo__nom", "nom"]},
        ),
        migrations.AddConstraint(
            model_name="cellulegrain",
            constraint=models.UniqueConstraint(
                fields=("silo", "nom"),
                name="unique_cellule_grain_par_silo",
            ),
        ),
        migrations.AddConstraint(
            model_name="silo",
            constraint=models.UniqueConstraint(
                fields=("site", "nom"),
                name="unique_silo_par_site",
            ),
        ),
    ]
