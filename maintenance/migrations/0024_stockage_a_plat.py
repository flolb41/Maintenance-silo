from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("maintenance", "0023_classer_cellules_prive_16x20"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockageAPlat",
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
                ("actif", models.BooleanField(default=True)),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stockages_a_plat",
                        to="maintenance.site",
                    ),
                ),
                (
                    "type_grain",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stockages_a_plat",
                        to="maintenance.typegrain",
                        verbose_name="type de grain",
                    ),
                ),
            ],
            options={
                "ordering": ["site__nom", "nom"],
            },
        ),
        migrations.CreateModel(
            name="ReleveStockageAPlat",
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
                (
                    "tonnage",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[MinValueValidator(Decimal("0"))],
                        verbose_name="tonnage (t)",
                    ),
                ),
                (
                    "releve_le",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("commentaire", models.TextField(blank=True)),
                (
                    "releve_par",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="releves_stockages_a_plat",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "stockage",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="releves",
                        to="maintenance.stockageaplat",
                    ),
                ),
            ],
            options={
                "ordering": ["-releve_le", "-pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="stockageaplat",
            constraint=models.UniqueConstraint(
                fields=("site", "nom"),
                name="unique_stockage_a_plat_par_site",
            ),
        ),
    ]
