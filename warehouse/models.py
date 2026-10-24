"""Recepción física de mercadería independiente de pedidos y liquidaciones.

Una orden documenta lo solicitado. Las líneas validadas de recepción
documentan lo efectivamente aceptado; NO representan por sí solas stock
disponible ni pagos a proveedores.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Trim, Upper
from django.utils import timezone

from core.models import TimeStampedModel


class GoodsReceipt(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        VALIDATED = "validated", "Validada"

    class DocumentType(models.TextChoices):
        GUIDE = "guide", "Guía de remisión"
        INVOICE = "invoice", "Factura"
        OTHER = "other", "Otro documento"

    reference = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    provider = models.ForeignKey(
        "catalog.Provider", on_delete=models.PROTECT,
        related_name="goods_receipts",
    )
    document_type = models.CharField(max_length=12, choices=DocumentType.choices)
    document_number = models.CharField(max_length=100, blank=True)
    received_on = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="goods_receipts_created",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="goods_receipts_validated", null=True, blank=True,
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_on", "-pk"]
        permissions = [
            ("view_receiving", "Puede consultar recepciones de mercadería"),
            ("manage_receiving", "Puede registrar borradores de recepción"),
            ("validate_receiving", "Puede validar recepciones de mercadería"),
        ]
        indexes = [
            models.Index(fields=["provider", "received_on"], name="wh_recept_provider_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "document_type", "document_number"],
                condition=Q(document_type="guide") & ~Q(document_number=""),
                name="wh_unique_supplier_guide",
            ),
            # Refuerza el índice anterior: la serie/número no distingue mayúsculas
            # y minúsculas ni espacios sobrantes al principio o al final.
            models.UniqueConstraint(
                Upper(Trim("document_number")), "provider", "document_type",
                condition=Q(document_type="guide") & ~Q(document_number=""),
                name="wh_unique_supplier_guide_ci",
            ),
        ]

    def __str__(self):
        return f"Recepción {self.pk or 'nueva'} - {self.provider_id}"


class GoodsReceiptLine(TimeStampedModel):
    receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.PROTECT, related_name="lines",
    )
    order_item = models.ForeignKey(
        "purchasing.PurchaseOrderItem", on_delete=models.PROTECT,
        related_name="receipt_lines",
    )
    quantity_arrived = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    quantity_accepted = models.PositiveIntegerField(default=0)
    quantity_observed = models.PositiveIntegerField(default=0)
    quantity_documented = models.PositiveIntegerField(null=True, blank=True)
    quantity_extra = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "order_item"], name="wh_line_unique_order_item",
            ),
            models.CheckConstraint(
                condition=Q(quantity_arrived__gte=1),
                name="wh_line_arrived_positive",
            ),
            models.CheckConstraint(
                condition=Q(quantity_accepted__lte=F("quantity_arrived")),
                name="wh_line_accepted_lte_arrived",
            ),
            models.CheckConstraint(
                condition=Q(quantity_observed__lte=F("quantity_arrived")),
                name="wh_line_observed_lte_arrived",
            ),
            models.CheckConstraint(
                condition=Q(quantity_arrived=F("quantity_accepted") + F("quantity_observed") + F("quantity_extra")),
                name="wh_line_quantities_balance",
            ),
        ]

    def clean(self):
        super().clean()
        if self.quantity_arrived != self.quantity_accepted + self.quantity_observed + self.quantity_extra:
            raise ValidationError(
                "Lo recibido debe ser igual a aceptado para el pedido, excedente conforme y observado."
            )
        if (self.receipt_id and self.order_item_id
                and self.receipt.provider_id != self.order_item.order.provider_id):
            raise ValidationError(
                "La editorial de la recepción no coincide con la del pedido."
            )


class GoodsReceiptEvent(TimeStampedModel):
    receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.PROTECT, related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="goods_receipt_events",
    )
    action = models.CharField(max_length=40)
    notes = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
