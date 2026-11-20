"""P-09: solicitud de mercadería antes de preparación; no altera stock."""
import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0012_stock_transfer_batch"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InternalStockRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("operation_name", models.CharField(blank=True, max_length=180)),
                ("responsible_name", models.CharField(max_length=180)),
                ("needed_on", models.DateField(blank=True, null=True)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("submitted", "Pendiente de aprobación"), ("approved", "Aprobada para preparación"), ("rejected", "Rechazada"), ("cancelled", "Anulada")], db_index=True, default="submitted", max_length=20)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_requests_created", to=settings.AUTH_USER_MODEL)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="stock_requests_approved", to=settings.AUTH_USER_MODEL)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_requests_origin", to="warehouse.warehouselocation")),
                ("destination", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_requests_destination", to="warehouse.warehouselocation")),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "permissions": [
                    ("view_internal_stock_requests", "Puede consultar solicitudes internas"),
                    ("manage_internal_stock_requests", "Puede registrar solicitudes internas"),
                    ("approve_internal_stock_requests", "Puede aprobar solicitudes internas"),
                ],
            },
        ),
        migrations.CreateModel(
            name="InternalStockRequestItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("product_name_snapshot", models.CharField(max_length=250)),
                ("product_code_snapshot", models.CharField(blank=True, max_length=100)),
                ("quantity_requested", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="internal_stock_request_items", to="catalog.product")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="warehouse.internalstockrequest")),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="InternalStockRequestEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("action", models.CharField(max_length=30)),
                ("from_status", models.CharField(blank=True, max_length=20)),
                ("to_status", models.CharField(max_length=20)),
                ("note", models.CharField(blank=True, max_length=500)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_request_events", to=settings.AUTH_USER_MODEL)),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="warehouse.internalstockrequest")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="internalstockrequest",
            constraint=models.CheckConstraint(condition=~Q(source=F("destination")), name="wh_req_distinct_locations"),
        ),
        migrations.AddIndex(
            model_name="internalstockrequest",
            index=models.Index(fields=["status", "created_at"], name="wh_req_status_date_idx"),
        ),
        migrations.AddConstraint(
            model_name="internalstockrequestitem",
            constraint=models.UniqueConstraint(fields=("request", "product"), name="wh_req_item_unique_product"),
        ),
        migrations.AddConstraint(
            model_name="internalstockrequestitem",
            constraint=models.CheckConstraint(condition=Q(quantity_requested__gte=1), name="wh_req_item_positive"),
        ),
    ]
