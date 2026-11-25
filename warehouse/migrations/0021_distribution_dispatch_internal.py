"""B4: orden interna, salida en tránsito y recepción sin doble stock.

No crea ni emite una GRE. Las existencias siguen trazables por StockEntry.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0020_warehouse_fair_event"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="distributionoperation", name="status",
            field=models.CharField(
                max_length=12, default="planned",
                choices=[
                    ("planned", "Por preparar"),
                    ("reserved", "Existencias reservadas"),
                    ("prepared", "Preparada"),
                    ("in_transit", "En tránsito"),
                    ("delivered", "Recibida en destino"),
                    ("cancelled", "Anulada"),
                ],
            ),
        ),
        migrations.CreateModel(
            name="DistributionDispatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("document_number", models.CharField(max_length=40, unique=True, blank=True)),
                ("status", models.CharField(
                    max_length=12, default="documented",
                    choices=[
                        ("documented", "Orden interna preparada"),
                        ("in_transit", "Despachada, en tránsito"),
                        ("received", "Recepción confirmada"),
                    ],
                )),
                ("evidence_kind", models.CharField(max_length=20, blank=True, choices=[
                    ("external_guide", "GRE emitida y verificada externamente"),
                    ("exception", "Excepción legal documentada"),
                ])),
                ("external_guide_reference", models.CharField(max_length=120, blank=True)),
                ("exception_justification", models.CharField(max_length=500, blank=True)),
                ("dispatched_at", models.DateTimeField(null=True, blank=True)),
                ("received_at", models.DateTimeField(null=True, blank=True)),
                ("recipient_name", models.CharField(max_length=180, blank=True)),
                ("notes", models.CharField(max_length=500, blank=True)),
                ("operation", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="dispatch", to="warehouse.distributionoperation",
                )),
                ("document_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="warehouse_dispatch_docs_created", to=settings.AUTH_USER_MODEL,
                )),
                ("dispatched_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, null=True, blank=True,
                    related_name="warehouse_dispatches_confirmed", to=settings.AUTH_USER_MODEL,
                )),
                ("received_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, null=True, blank=True,
                    related_name="warehouse_dispatch_receipts_confirmed", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.CreateModel(
            name="DistributionDispatchLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("dispatch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="lines", to="warehouse.distributiondispatch",
                )),
                ("reservation", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="dispatch_line", to="warehouse.distributionstockreservation",
                )),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.AddConstraint(
            model_name="distributiondispatchline",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="wh_dispatch_line_positive",
            ),
        ),
    ]
