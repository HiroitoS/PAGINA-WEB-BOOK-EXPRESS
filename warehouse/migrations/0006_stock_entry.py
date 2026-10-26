from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0005_incident_timestamps_labels"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="StockEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("quantity_available", models.PositiveIntegerField()),
                ("quantity_quarantined", models.PositiveIntegerField(default=0)),
                ("quantity_extra", models.PositiveIntegerField(default=0)),
                ("posted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_entries_posted", to=settings.AUTH_USER_MODEL)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_entries", to="catalog.product")),
                ("receipt_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="stock_entry", to="warehouse.goodsreceiptline")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddConstraint(
            model_name="stockentry",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity_extra__lte=models.F("quantity_available")),
                name="wh_stock_extra_within_available",
            ),
        ),
    ]
