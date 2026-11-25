"""Documentos de proveedor, línea de pedido y auditoría, sin modificar inventario."""
import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Trim, Upper


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierInvoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("document_number", models.CharField(max_length=80)),
                ("issued_on", models.DateField()),
                ("currency", models.CharField(default="PEN", max_length=3)),
                ("total_document", models.DecimalField(
                    decimal_places=2, max_digits=14,
                    validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                )),
                ("status", models.CharField(
                    choices=[("draft", "Pendiente de conciliación")],
                    default="draft", max_length=12,
                )),
                ("notes", models.CharField(blank=True, max_length=1000)),
                ("created_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="supplier_invoices_created", to=settings.AUTH_USER_MODEL,
                )),
                ("provider", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="supplier_invoices", to="catalog.provider",
                )),
            ],
            options={
                "ordering": ["-issued_on", "-pk"],
                "permissions": [
                    ("view_supplier_invoices", "Puede consultar facturas de editoriales"),
                    ("manage_supplier_invoices", "Puede registrar y corregir borradores de factura"),
                ],
            },
        ),
        migrations.CreateModel(
            name="SupplierInvoiceLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("quantity_billed", models.PositiveIntegerField(
                    validators=[django.core.validators.MinValueValidator(1)],
                )),
                ("unit_cost_billed", models.DecimalField(
                    decimal_places=2, max_digits=12,
                    validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                )),
                ("expected_unit_cost_snapshot", models.DecimalField(decimal_places=2, max_digits=12)),
                ("invoice", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="items", to="purchasing.supplierinvoice",
                )),
                ("order_item", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="supplier_invoice_items", to="purchasing.purchaseorderitem",
                )),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="SupplierInvoiceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("action", models.CharField(max_length=30)),
                ("detail", models.JSONField(default=dict)),
                ("actor", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="supplier_invoice_events", to=settings.AUTH_USER_MODEL,
                )),
                ("invoice", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="events", to="purchasing.supplierinvoice",
                )),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="supplierinvoice",
            constraint=models.UniqueConstraint(
                Upper(Trim("document_number")), "provider",
                name="purch_invoice_provider_number_ci",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplierinvoice",
            constraint=models.CheckConstraint(
                condition=Q(total_document__gte=0),
                name="purch_invoice_total_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplierinvoiceline",
            constraint=models.UniqueConstraint(
                fields=["invoice", "order_item"],
                name="purch_invoice_once_per_order_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplierinvoiceline",
            constraint=models.CheckConstraint(
                condition=Q(quantity_billed__gte=1),
                name="purch_invoice_line_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplierinvoiceline",
            constraint=models.CheckConstraint(
                condition=Q(unit_cost_billed__gte=0),
                name="purch_invoice_cost_nonnegative",
            ),
        ),
    ]
