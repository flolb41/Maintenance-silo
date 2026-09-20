from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0029_budget_annuel_site")]
    operations = [
        migrations.CreateModel(
            name="PiecePanne",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("quantite", models.PositiveIntegerField(
                    validators=[django.core.validators.MinValueValidator(1)])),
                ("statut", models.CharField(choices=[("reservee", "Réservée"), ("consommee", "Consommée"), (
                    "restituee", "Restituée")], default="reservee", max_length=12)),
                ("commentaire", models.CharField(blank=True, max_length=255)),
                ("reservee_le", models.DateTimeField(auto_now_add=True)),
                ("consommee_le", models.DateTimeField(blank=True, null=True)),
                ("restituee_le", models.DateTimeField(blank=True, null=True)),
                ("consommee_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                 related_name="pieces_consommees", to=settings.AUTH_USER_MODEL)),
                ("panne", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                 related_name="pieces", to="maintenance.panne")),
                ("piece", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                 related_name="reservations_pannes", to="maintenance.piecedetachee")),
                ("reservee_par", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                 related_name="pieces_reservees", to=settings.AUTH_USER_MODEL)),
                ("restituee_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                 related_name="pieces_restituees", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-reservee_le"]},
        ),
    ]
