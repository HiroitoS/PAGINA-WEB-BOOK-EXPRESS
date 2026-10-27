from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0006_stock_entry")]
    operations = [
        migrations.AddField(
            model_name="stockentry",
            name="unit_cost_snapshot",
            field=models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True),
        ),
    ]
