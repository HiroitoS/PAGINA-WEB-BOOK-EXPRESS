"""P-08.3: traslado masivo por guía, confirmación y idempotencia de grupo."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0011_stock_transfer"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockTransferBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_transfer_batches_created", to=settings.AUTH_USER_MODEL)),
                ("destination", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_batches_received", to="warehouse.warehouselocation")),
                ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_batches", to="warehouse.goodsreceipt")),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_batches_dispatched", to="warehouse.warehouselocation")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddField(
            model_name="stocktransfer",
            name="batch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transfers", to="warehouse.stocktransferbatch"),
        ),
    ]
