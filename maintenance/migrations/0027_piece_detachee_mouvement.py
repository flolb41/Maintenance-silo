from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0026_equipement_parent")]

    operations = [
        migrations.CreateModel(
            name="PieceDetachee",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(max_length=100)),
                ("nom", models.CharField(max_length=150)),
                ("stock", models.PositiveIntegerField(default=0)),
                ("seuil_alerte", models.PositiveIntegerField(default=1)),
                ("emplacement", models.CharField(blank=True, max_length=100)),
                ("fournisseur", models.CharField(blank=True, max_length=150)),
                ("actif", models.BooleanField(default=True)),
                ("creee_le", models.DateTimeField(auto_now_add=True)),
                ("site", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                 related_name="pieces_detachees", to="maintenance.site")),
            ],
            options={"ordering": ["nom"]},
        ),
        migrations.CreateModel(
            name="MouvementPiece",
            fields=[
                ("id", models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name="ID")),
                ("type_mouvement", models.CharField(choices=[
                 ("entree", "Entrée"), ("sortie", "Sortie")], max_length=10)),
                ("quantite", models.PositiveIntegerField(
                    validators=[django.core.validators.MinValueValidator(1)])),
                ("commentaire", models.CharField(blank=True, max_length=255)),
                ("creee_le", models.DateTimeField(auto_now_add=True)),
                ("effectue_par", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("piece", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name="mouvements", to="maintenance.piecedetachee")),
            ],
            options={"ordering": ["-creee_le"]},
        ),
        migrations.AddConstraint(
            model_name="piecedetachee",
            constraint=models.UniqueConstraint(
                fields=("site", "reference"), name="unique_piece_reference_site"),
        ),
    ]
