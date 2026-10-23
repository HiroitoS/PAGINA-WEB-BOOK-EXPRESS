"""ERP purchases: an order preserves what was requested, not what arrived.

Stock and received quantities belong to immutable goods-receipt movements in the
warehouse domain. Never infer available stock from a purchase order.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel


class PurchaseOrder(TimeStampedModel):
    class Origin(models.TextChoices):
        ADOPTION = "adoption", "Adopción"
        MANUAL = "manual", "Pedido independiente"

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        APPROVED = "approved", "Aprobado"
        SENT = "sent", "Enviado"
        PARTIALLY_RECEIVED = "partially_received", "Recibido parcialmente"
        RECEIVED = "received", "Recibido completo"
        CLOSED_PARTIAL = "closed_partial", "Cerrado con saldo"
        CANCELLED = "cancelled", "Anulado"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    origin = models.CharField(max_length=12, choices=Origin.choices)
    provider = models.ForeignKey("catalog.Provider", on_delete=models.PROTECT, related_name="purchase_orders")
    school = models.ForeignKey("crm.School", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_orders")
    campaign = models.ForeignKey("crm.Campaign", on_delete=models.PROTECT, related_name="purchase_orders")
    adoption = models.ForeignKey("crm.Adoption", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_orders")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    provider_name_snapshot = models.CharField(max_length=150)
    school_name_snapshot = models.CharField(max_length=220, blank=True)
    campaign_name_snapshot = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_purchase_orders")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_purchase_orders")
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        permissions = [
            ("view_purchasing", "Puede consultar pedidos a editoriales"),
            ("manage_purchasing", "Puede preparar pedidos a editoriales"),
            ("approve_purchasing", "Puede aprobar pedidos a editoriales"),
            ("record_purchase_dispatch", "Puede registrar el envío de pedidos"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(origin="adoption", adoption__isnull=False, school__isnull=False)
                           | Q(origin="manual", adoption__isnull=True)),
                name="purch_order_origin_valid",
            ),
            models.UniqueConstraint(
                fields=["adoption", "provider"],
                condition=Q(adoption__isnull=False),
                name="purch_order_once_per_adoption_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "campaign", "status"], name="purch_ord_provider_cmp_idx"),
            models.Index(fields=["school", "campaign"], name="purch_ord_school_cmp_idx"),
        ]

    def clean(self):
        super().clean()
        if self.origin == self.Origin.ADOPTION and not self.adoption_id:
            raise ValidationError({"adoption": "Selecciona una adopción confirmada."})
        if self.origin == self.Origin.MANUAL and self.adoption_id:
            raise ValidationError({"adoption": "Un pedido independiente no puede vincular una adopción."})
        if self.adoption_id:
            if self.school_id != self.adoption.school_id:
                raise ValidationError({"school": "El colegio debe coincidir con el de la adopción."})
            if self.campaign_id != self.adoption.campaign_id:
                raise ValidationError({"campaign": "La campaña debe coincidir con la adopción."})

    def __str__(self):
        return f"Pedido {self.reference} - {self.provider_name_snapshot}"


class PurchaseOrderItem(TimeStampedModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="purchase_order_items")
    adoption_item = models.ForeignKey("crm.AdoptionItem", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_items")
    product_name_snapshot = models.CharField(max_length=250)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    quantity_ordered = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_supplier_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    currency = models.CharField(max_length=3, default="PEN")

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity_ordered__gte=1), name="purch_item_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_supplier_cost__gte=0), name="purch_item_cost_nonnegative"),
            models.UniqueConstraint(fields=["order", "adoption_item"], condition=Q(adoption_item__isnull=False), name="purch_item_unique_adoption_line"),
        ]

    def clean(self):
        super().clean()
        if self.order_id and self.product_id and self.product.provider_id != self.order.provider_id:
            raise ValidationError({"product": "El producto no corresponde a la editorial del pedido."})
        if self.adoption_item_id:
            if not self.order_id or self.order.origin != PurchaseOrder.Origin.ADOPTION:
                raise ValidationError({"adoption_item": "El ítem de adopción requiere un pedido originado por adopción."})
            if self.adoption_item.adoption_id != self.order.adoption_id:
                raise ValidationError({"adoption_item": "El ítem no pertenece a la adopción del pedido."})
            if self.adoption_item.product_id != self.product_id:
                raise ValidationError({"product": "El producto difiere del ítem adoptado."})

    def __str__(self):
        return f"{self.product_name_snapshot} ({self.quantity_ordered})"


class PurchaseOrderEvent(TimeStampedModel):
    """Append-only event log; service layer will enforce who may create events."""

    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_order_events")
    event_type = models.CharField(max_length=40)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    notes = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["order", "created_at"], name="purch_event_order_time_idx")]
