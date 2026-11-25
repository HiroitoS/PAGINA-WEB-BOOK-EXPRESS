"""Preparación logística por lote y borrador documental previo a GRE.

No se emiten guías ni se mueven existencias con esta migración.
"""
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0015_receipt_cancelled"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="distributionoperation", name="status",
            field=models.CharField(
                max_length=12, default="planned", choices=[
                    ("planned", "Por preparar"),
                    ("reserved", "Existencias reservadas"),
                    ("prepared", "Preparada"),
                    ("cancelled", "Anulada"),
                ],
            ),
        ),
        migrations.CreateModel(
            name="DistributionStockReservation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("status", models.CharField(
                    max_length=10, default="active", db_index=True,
                    choices=[("active", "Reservada"), ("released", "Liberada")],
                )),
                ("counted_quantity", models.PositiveIntegerField(blank=True, null=True)),
                ("counted_at", models.DateTimeField(blank=True, null=True)),
                ("counted_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="warehouse_reservations_counted",
                )),
                ("operation", models.ForeignKey(
                    to="warehouse.distributionoperation", on_delete=django.db.models.deletion.PROTECT,
                    related_name="stock_reservations",
                )),
                ("stock_entry", models.ForeignKey(
                    to="warehouse.stockentry", on_delete=django.db.models.deletion.PROTECT,
                    related_name="distribution_reservations",
                )),
                ("source", models.ForeignKey(
                    to="warehouse.warehouselocation", on_delete=django.db.models.deletion.PROTECT,
                    related_name="distribution_reservations",
                )),
                ("reserved_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                    related_name="warehouse_reservations_created",
                )),
            ],
            options={"ordering": ["stock_entry_id", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="distributionstockreservation",
            constraint=models.UniqueConstraint(
                fields=["operation", "stock_entry"], name="wh_prep_unique_entry",
            ),
        ),
        migrations.AddConstraint(
            model_name="distributionstockreservation",
            constraint=models.CheckConstraint(
                condition=Q(quantity__gte=1), name="wh_prep_positive_quantity",
            ),
        ),
        migrations.CreateModel(
            name="DistributionTransportDraft",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("issuer_ruc", models.CharField(max_length=11, blank=True)),
                ("departure_address", models.CharField(max_length=300, blank=True)),
                ("destination_address", models.CharField(max_length=300, blank=True)),
                ("destination_id_number", models.CharField(max_length=20, blank=True)),
                ("destination_name", models.CharField(max_length=180, blank=True)),
                ("transport_mode", models.CharField(max_length=10, blank=True, choices=[
                    ("private", "Transporte privado"), ("public", "Transporte público"),
                ])),
                ("transfer_reason", models.CharField(max_length=30, blank=True, choices=[
                    ("consignment", "Consignación"),
                    ("company_transfer", "Entre establecimientos"),
                    ("sale", "Venta"),
                    ("other", "Otro motivo (verificar)"),
                ])),
                ("departure_on", models.DateField(null=True, blank=True)),
                ("license_plate", models.CharField(max_length=15, blank=True)),
                ("driver_document", models.CharField(max_length=20, blank=True)),
                ("driver_license", models.CharField(max_length=30, blank=True)),
                ("carrier_ruc", models.CharField(max_length=11, blank=True)),
                ("gross_weight_kg", models.DecimalField(
                    max_digits=12, decimal_places=3, blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0.001)],
                )),
                ("notes", models.CharField(max_length=500, blank=True)),
                ("operation", models.OneToOneField(
                    to="warehouse.distributionoperation", on_delete=django.db.models.deletion.PROTECT,
                    related_name="transport_draft",
                )),
                ("updated_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                    related_name="warehouse_transport_drafts_updated",
                )),
            ],
            options={"ordering": ["-updated_at"]},
        ),
    ]
