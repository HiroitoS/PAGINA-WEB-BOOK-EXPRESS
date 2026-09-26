from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from catalog.models import Product
from core.models import TimeStampedModel

from .opportunity import Opportunity


class CommercialQuotation(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        SENT = "sent", "Enviada"
        ACCEPTED = "accepted", "Aceptada"
        REJECTED = "rejected", "Rechazada"
        SUPERSEDED = "superseded", "Reemplazada"

    class DiscountApprovalStatus(models.TextChoices):
        NOT_REQUIRED = "not_required", "No requerida"
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobada"

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name="quotations",
        verbose_name="Oportunidad",
    )
    source_projection = models.ForeignKey(
        "CommercialProjection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quotations",
        verbose_name="Proyección de origen",
    )
    version = models.PositiveSmallIntegerField(
        verbose_name="Versión",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name="Estado",
    )
    school_name_snapshot = models.CharField(
        max_length=220,
        verbose_name="Colegio al cotizar",
    )
    campaign_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="Campaña al cotizar",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )
    requires_discount_approval = models.BooleanField(
        default=False,
        verbose_name="Requiere aprobación de descuento",
    )
    discount_approval_status = models.CharField(
        max_length=20,
        choices=DiscountApprovalStatus.choices,
        default=DiscountApprovalStatus.NOT_REQUIRED,
        db_index=True,
        verbose_name="Estado de aprobación de descuento",
    )
    discount_approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de aprobación de descuento",
    )
    discount_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_crm_quotation_discounts",
        verbose_name="Descuento aprobado por",
    )
    discount_approval_note = models.TextField(
        blank=True,
        verbose_name="Observación de aprobación",
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de envío",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_crm_quotations",
        verbose_name="Enviada por",
    )
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de aceptación",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_crm_quotations",
        verbose_name="Aceptada por",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_quotations",
        verbose_name="Creada por",
    )

    class Meta:
        verbose_name = "Cotización comercial"
        verbose_name_plural = "Cotizaciones comerciales"
        ordering = ["opportunity", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "version"],
                name="crm_quote_unique_opp_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["opportunity", "status"],
                name="crm_quote_opp_status_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.opportunity.school.name} - "
            f"v{self.version} - {self.get_status_display()}"
        )


class CommercialQuotationItem(TimeStampedModel):
    quotation = models.ForeignKey(
        CommercialQuotation,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Cotización",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="crm_quotation_items",
        verbose_name="Producto",
    )
    product_name_snapshot = models.CharField(
        max_length=250,
        verbose_name="Producto al cotizar",
    )
    provider_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="Editorial al cotizar",
    )
    level_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Nivel al cotizar",
    )
    grade_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Grado al cotizar",
    )
    area_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Área al cotizar",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Cantidad estimada",
    )
    pvp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="PVP",
    )
    supplier_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Costo editorial",
    )
    school_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio colegio",
    )
    school_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
        ],
        verbose_name="Descuento colegio (%)",
    )
    parent_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio sugerido PPFF",
    )
    school_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Comisión colegio",
    )
    price_year_snapshot = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Año del precio usado",
    )
    price_campaign_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Campaña del precio usado",
    )
    uses_reference_price = models.BooleanField(
        default=False,
        verbose_name="Usa precio referencial anterior",
    )

    class Meta:
        verbose_name = "Ítem de cotización"
        verbose_name_plural = "Ítems de cotización"
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["quotation", "product"],
                name="crm_quote_item_prod_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.quotation} - "
            f"{self.product_name_snapshot}"
        )
