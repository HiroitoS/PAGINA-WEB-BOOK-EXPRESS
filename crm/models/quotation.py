from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import Product
from core.models import TimeStampedModel

from .opportunity import Opportunity


class CommercialQuotation(TimeStampedModel):
    class CommercialLine(models.TextChoices):
        SCHOOL_TEXT = "school_text", "Texto escolar"
        READING_PLAN = "reading_plan", "Plan lector"
        OTHER = "other", "Sin clasificar"

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

    class SaleMode(models.TextChoices):
        POINT_OF_SALE = "point_of_sale", "Punto de venta / librería"
        FAIR = "fair", "Feria"
        CONSIGNMENT = "consignment", "Consignación"

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
    internal_code = models.CharField(
        max_length=40,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Código interno",
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
    primary_contact_name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        default="",
        verbose_name="Contacto al cotizar",
    )
    primary_contact_position_snapshot = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Cargo del contacto al cotizar",
    )
    primary_contact_phone_snapshot = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Teléfono del contacto al cotizar",
    )
    primary_contact_email_snapshot = models.EmailField(
        blank=True,
        default="",
        verbose_name="Correo del contacto al cotizar",
    )
    advisor_name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        default="",
        verbose_name="Asesor al cotizar",
    )
    advisor_phone_snapshot = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Celular del asesor al cotizar",
    )
    advisor_whatsapp_snapshot = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="WhatsApp del asesor al cotizar",
    )
    commercial_line = models.CharField(
        max_length=20,
        choices=CommercialLine.choices,
        default=CommercialLine.OTHER,
        db_index=True,
        verbose_name="Línea comercial",
    )
    sale_mode = models.CharField(
        max_length=20,
        choices=SaleMode.choices,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Modalidad de venta",
    )
    service_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de atención",
    )
    service_end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de fin de feria",
    )
    fair_start_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Hora de inicio de feria",
    )
    fair_end_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Hora de fin de feria",
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
    reopened_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de reapertura de negociación",
    )
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reopened_crm_quotations",
        verbose_name="Negociación reabierta por",
    )
    reopen_reason = models.TextField(
        blank=True,
        verbose_name="Motivo de reapertura",
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

    def _build_internal_code(self):
        if self.pk is None:
            return None

        year = self.opportunity.campaign.year
        return (
            f"BE-COT-{year}-"
            f"{self.pk:06d}-V{self.version:02d}"
        )

    def save(self, *args, **kwargs):
        needs_internal_code = not self.internal_code
        super().save(*args, **kwargs)

        if needs_internal_code:
            internal_code = self._build_internal_code()
            type(self).objects.filter(pk=self.pk).update(
                internal_code=internal_code
            )
            self.internal_code = internal_code

    def __str__(self):
        return (
            f"{self.opportunity.school.name} - "
            f"v{self.version} - {self.get_status_display()}"
        )


class CommercialQuotationItem(TimeStampedModel):
    class CommercialLine(models.TextChoices):
        SCHOOL_TEXT = "school_text", "Texto escolar"
        READING_PLAN = "reading_plan", "Plan lector"
        OTHER = "other", "Otra línea"

    class CommissionMode(models.TextChoices):
        PER_UNIT = "per_unit", "Por unidad"
        TOTAL = "total", "Monto total"

    class ProfitabilityBand(models.TextChoices):
        GREEN = "green", "Verde"
        AMBER = "amber", "Ámbar"
        RED = "red", "Rojo"
        LOSS = "loss", "Pérdida"
        UNCLASSIFIED = "unclassified", "Sin clasificar"

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
    product_code_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Código de producto al cotizar",
    )
    product_type_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Tipo de producto al cotizar",
    )
    commercial_line = models.CharField(
        max_length=20,
        choices=CommercialLine.choices,
        default=CommercialLine.OTHER,
        verbose_name="Línea comercial",
    )
    reading_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ],
        verbose_name="Mes de lectura",
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
    supplier_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        verbose_name="Descuento editorial (%)",
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
        verbose_name="Comisión unitaria autorizada",
    )
    commission_mode = models.CharField(
        max_length=20,
        choices=CommissionMode.choices,
        default=CommissionMode.PER_UNIT,
        verbose_name="Modalidad de comisión",
    )
    commission_input_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Comisión ingresada",
    )
    commercial_margin_unit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Margen comercial unitario",
    )
    commercial_margin_total = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Margen comercial proyectado",
    )
    commercial_margin_percent = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Margen comercial (%)",
    )
    profitability_band = models.CharField(
        max_length=20,
        choices=ProfitabilityBand.choices,
        default=ProfitabilityBand.UNCLASSIFIED,
        verbose_name="Semáforo de rentabilidad",
    )
    max_green_discount_percent = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Descuento máximo para mantener verde (%)",
    )
    green_discount_headroom_points = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Margen de negociación hasta verde (puntos)",
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
