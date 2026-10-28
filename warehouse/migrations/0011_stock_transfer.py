"""P-08.2: traslado entre ubicaciones de stock conforme por lote."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0010_stock_entry_location"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockTransfer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("unit_cost_snapshot", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_transfers_created", to=settings.AUTH_USER_MODEL)),
                ("destination", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfers_received", to="warehouse.warehouselocation")),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfers_dispatched", to="warehouse.warehouselocation")),
                ("stock_entry", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfers", to="warehouse.stockentry")),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "permissions": [
                    ("view_stock_transfers", "Puede consultar traslados de mercadería"),
                    ("manage_stock_transfers", "Puede registrar traslados de mercadería"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="stocktransfer",
            constraint=models.CheckConstraint(condition=Q(quantity__gte=1), name="wh_transfer_quantity_positive"),
        ),
        migrations.AddConstraint(
            model_name="stocktransfer",
            constraint=models.CheckConstraint(condition=~Q(source=F("destination")), name="wh_transfer_distinct_locations"),
        ),
    ]
