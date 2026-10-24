"""Campos de conciliación documental y excedentes físicos, sin asumir datos históricos."""
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0002_guia_unique_ci")]
    operations = [
        migrations.AddField(model_name="goodsreceiptline", name="quantity_documented", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="goodsreceiptline", name="quantity_extra", field=models.PositiveIntegerField(default=0)),
        migrations.RemoveConstraint(model_name="goodsreceiptline", name="wh_line_quantities_balance"),
        migrations.AddConstraint(model_name="goodsreceiptline", constraint=models.CheckConstraint(
            condition=Q(quantity_arrived=F("quantity_accepted") + F("quantity_observed") + F("quantity_extra")),
            name="wh_line_quantities_balance",
        )),
    ]
