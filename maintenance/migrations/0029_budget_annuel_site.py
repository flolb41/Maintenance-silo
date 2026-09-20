from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0028_site_activites")]
    operations = [
        migrations.CreateModel(name="BudgetAnnuelSite", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("annee", models.PositiveSmallIntegerField()), ("montant_budget_ttc", models.DecimalField(
            decimal_places=2, max_digits=12)), ("seuil_alerte_pct", models.PositiveSmallIntegerField(default=80)), ("site", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="budgets_annuels", to="maintenance.site"))], options={"ordering": ["-annee", "site__nom"]}),
        migrations.AddConstraint(model_name="budgetannuelsite", constraint=models.UniqueConstraint(
            fields=("site", "annee"), name="unique_budget_annuel_site")),
    ]
