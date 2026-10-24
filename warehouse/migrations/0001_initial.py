# Migración inicial del módulo de recepción de mercadería.
import django.db.models.deletion
import django.utils.timezone
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("purchasing", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GoodsReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("document_type", models.CharField(choices=[("guide", "Guía de remisión"), ("invoice", "Factura"), ("other", "Otro documento")], max_length=12)),
                ("document_number", models.CharField(blank=True, max_length=100)),
                ("received_on", models.DateField(default=django.utils.timezone.localdate)),
                ("status", models.CharField(choices=[("draft", "Borrador"), ("validated", "Validada")], db_index=True, default="draft", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_receipts_created", to=settings.AUTH_USER_MODEL)),
                ("provider", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_receipts", to="catalog.provider")),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("validated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="goods_receipts_validated", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-received_on", "-pk"],
                "permissions": [("view_receiving", "Puede consultar recepciones de mercadería"), ("manage_receiving", "Puede registrar borradores de recepción"), ("validate_receiving", "Puede validar recepciones de mercadería")],
            },
        ),
        migrations.CreateModel(
            name="GoodsReceiptLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("quantity_arrived", models.PositiveIntegerField(validators=[__import__("django").core.validators.MinValueValidator(1)])),
                ("quantity_accepted", models.PositiveIntegerField(default=0)),
                ("quantity_observed", models.PositiveIntegerField(default=0)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("order_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipt_lines", to="purchasing.purchaseorderitem")),
                ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="warehouse.goodsreceipt")),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="GoodsReceiptEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("action", models.CharField(max_length=40)),
                ("notes", models.TextField(blank=True)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_receipt_events", to=settings.AUTH_USER_MODEL)),
                ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="warehouse.goodsreceipt")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.AddIndex(
            model_name="goodsreceipt", index=models.Index(fields=["provider", "received_on"], name="wh_recept_provider_idx"),
        ),
        migrations.AddConstraint(
            model_name="goodsreceiptline", constraint=models.UniqueConstraint(fields=("receipt", "order_item"), name="wh_line_unique_order_item"),
        ),
        migrations.AddConstraint(
            model_name="goodsreceiptline", constraint=models.CheckConstraint(condition=models.Q(quantity_arrived__gte=1), name="wh_line_arrived_positive"),
        ),
        migrations.AddConstraint(
            model_name="goodsreceiptline", constraint=models.CheckConstraint(condition=models.Q(quantity_accepted__lte=models.F("quantity_arrived")), name="wh_line_accepted_lte_arrived"),
        ),
        migrations.AddConstraint(
            model_name="goodsreceiptline", constraint=models.CheckConstraint(condition=models.Q(quantity_observed__lte=models.F("quantity_arrived")), name="wh_line_observed_lte_arrived"),
        ),
    ]
