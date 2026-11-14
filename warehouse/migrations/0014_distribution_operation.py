"""Operaciones de distribución con modalidad logística versionada, sin mover stock."""
import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0013_internal_stock_request"),
        ("crm", "0046_protect_crm_work_item_task"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DistributionOperation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("original_mode", models.CharField(blank=True, max_length=20, choices=[
                    ("point_of_sale", "Punto de venta"), ("fair", "Feria"), ("consignment", "Consignación"),
                ])),
                ("mode", models.CharField(max_length=20, choices=[
                    ("point_of_sale", "Punto de venta"), ("fair", "Feria"), ("consignment", "Consignación"),
                ])),
                ("operation_name", models.CharField(max_length=180)),
                ("responsible_name", models.CharField(max_length=180)),
                ("scheduled_on", models.DateField(null=True, blank=True)),
                ("scheduled_until", models.DateField(null=True, blank=True)),
                ("notes", models.CharField(max_length=500, blank=True)),
                ("status", models.CharField(max_length=12, default="planned", choices=[
                    ("planned", "Por preparar"), ("cancelled", "Anulada"),
                ])),
                ("adoption", models.ForeignKey(to="crm.adoption", on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_distribution_operations")),
                ("school", models.ForeignKey(to="crm.school", on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_distribution_operations")),
                ("source", models.ForeignKey(to="warehouse.warehouselocation", on_delete=django.db.models.deletion.PROTECT, related_name="distribution_operations_origin")),
                ("destination", models.ForeignKey(to="warehouse.warehouselocation", on_delete=django.db.models.deletion.PROTECT, related_name="distribution_operations_destination")),
                ("created_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name="distribution_operations_created")),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "permissions": [
                    ("view_distribution_operations", "Puede consultar distribución de mercadería"),
                    ("manage_distribution_operations", "Puede planificar y modificar distribución"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DistributionOperationLine",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("product_name_snapshot", models.CharField(max_length=250)),
                ("quantity_planned", models.PositiveIntegerField(validators=[
                    django.core.validators.MinValueValidator(1),
                ])),
                ("operation", models.ForeignKey(to="warehouse.distributionoperation", on_delete=django.db.models.deletion.PROTECT, related_name="items")),
                ("product", models.ForeignKey(to="catalog.product", on_delete=django.db.models.deletion.PROTECT, related_name="distribution_operation_lines")),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="DistributionOperationEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("action", models.CharField(max_length=24)),
                ("reason", models.CharField(max_length=500, blank=True)),
                ("previous", models.JSONField(default=dict, blank=True)),
                ("current", models.JSONField(default=dict, blank=True)),
                ("actor", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name="distribution_operation_events")),
                ("operation", models.ForeignKey(to="warehouse.distributionoperation", on_delete=django.db.models.deletion.PROTECT, related_name="events")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="distributionoperation",
            constraint=models.CheckConstraint(
                condition=~Q(source=F("destination")),
                name="wh_distribution_locations_differ",
            ),
        ),
        migrations.AddConstraint(
            model_name="distributionoperationline",
            constraint=models.UniqueConstraint(
                fields=["operation", "product"], name="wh_distribution_item_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="distributionoperationline",
            constraint=models.CheckConstraint(
                condition=Q(quantity_planned__gte=1),
                name="wh_distribution_quantity_positive",
            ),
        ),
    ]
