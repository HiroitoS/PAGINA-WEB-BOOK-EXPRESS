from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import Product
from core.models import TimeStampedModel

from .campaign import Campaign
from .opportunity import Opportunity
from .quotation import CommercialQuotation, CommercialQuotationItem
from .school import School, SchoolContact


class Adoption(TimeStampedModel):
    class SaleMode(models.TextChoices):
        POINT_OF_SALE = "point_of_sale", "Punto de venta / librería"
        FAIR = "fair", "Feria"
        CONSIGNMENT = "consignment", "Consignación"

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name="adoptions",
        verbose_name="Oportunidad",
    )
    quotation = models.OneToOneField(
        CommercialQuotation,
        on_delete=models.PROTECT,
        related_name="adoption",
        verbose_name="Cotización aceptada",
    )
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="adoptions",
        verbose_name="Colegio",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        related_name="adoptions",
        verbose_name="Campaña",
    )
    version = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Versión",
    )
    is_current = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Versión vigente",
    )
    school_name_snapshot = models.CharField(
        max_length=220,
        verbose_name="Colegio al confirmar",
    )
    campaign_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="Campaña al confirmar",
    )
    advisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_adoptions_as_advisor",
        verbose_name="Asesor responsable",
    )
    advisor_name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Asesor al confirmar",
    )
    advisor_phone_snapshot = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Celular del asesor al confirmar",
    )
    advisor_whatsapp_snapshot = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="WhatsApp del asesor al confirmar",
    )
    authorized_contact = models.ForeignKey(
        SchoolContact,
        on_delete=models.PROTECT,
        related_name="authorized_adoptions",
        verbose_name="Directivo que autorizó",
    )
    authorized_contact_name_snapshot = models.CharField(
        max_length=180,
        verbose_name="Directivo al confirmar",
    )
    authorized_contact_position_snapshot = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Cargo del directivo al confirmar",
    )
    authorized_contact_phone_snapshot = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Teléfono del directivo al confirmar",
    )
    authorized_contact_email_snapshot = models.EmailField(
        blank=True,
        default="",
        verbose_name="Correo del directivo al confirmar",
    )
    signed_at = models.DateTimeField(
        verbose_name="Fecha de firma / aprobación",
    )
    confirmed_at = models.DateTimeField(
        verbose_name="Fecha de confirmación",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_crm_adoptions",
        verbose_name="Confirmada por",
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

    class Meta:
        verbose_name = "Adopción"
        verbose_name_plural = "Adopciones"
        ordering = ["-confirmed_at", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "version"],
                name="crm_adoption_unique_opp_version",
            ),
            models.UniqueConstraint(
                fields=["opportunity"],
                condition=models.Q(is_current=True),
                name="crm_adoption_one_current",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "campaign", "is_current"],
                name="crm_adopt_school_cmp_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.school_name_snapshot} - "
            f"{self.campaign_name_snapshot} - v{self.version}"
        )


class AdoptionItem(TimeStampedModel):
    adoption = models.ForeignKey(
        Adoption,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Adopción",
    )
    quotation_item = models.ForeignKey(
        CommercialQuotationItem,
        on_delete=models.PROTECT,
        related_name="adoption_items",
        verbose_name="Ítem de cotización origen",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="crm_adoption_items",
        verbose_name="Producto",
    )
    product_name_snapshot = models.CharField(
        max_length=250,
        verbose_name="Producto adoptado",
    )
    provider_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="Editorial adoptada",
    )
    level_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Nivel",
    )
    grade_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Grado",
    )
    area_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Área",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Cantidad confirmada",
    )
    pvp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="PVP confirmado",
    )
    supplier_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Costo editorial confirmado",
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
        verbose_name="Descuento editorial confirmado (%)",
    )
    school_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio colegio confirmado",
    )
    parent_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio PPFF confirmado",
    )
    school_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Comisión colegio confirmada",
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

    class Meta:
        verbose_name = "Ítem de adopción"
        verbose_name_plural = "Ítems de adopción"
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["adoption", "product"],
                name="crm_adopt_item_prod_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.adoption} - "
            f"{self.product_name_snapshot}"
        )
