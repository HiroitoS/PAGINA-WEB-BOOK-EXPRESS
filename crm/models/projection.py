from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from catalog.models import Grade, Product
from core.models import TimeStampedModel

from .opportunity import Opportunity
from .school import SchoolEducationalService


class CommercialProjection(TimeStampedModel):
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name="projections",
        verbose_name="Oportunidad",
    )
    version = models.PositiveSmallIntegerField(
        verbose_name="Versión",
    )
    is_current = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Versión vigente",
    )
    school_name_snapshot = models.CharField(
        max_length=220,
        verbose_name="Colegio al proyectar",
    )
    campaign_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="Campaña al proyectar",
    )
    campaign_year_snapshot = models.PositiveSmallIntegerField(
        verbose_name="Año de campaña",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_projections",
        verbose_name="Creada por",
    )

    class Meta:
        verbose_name = "Proyección comercial"
        verbose_name_plural = "Proyecciones comerciales"
        ordering = ["opportunity", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "version"],
                name="crm_proj_unique_opp_version",
            ),
            models.UniqueConstraint(
                fields=["opportunity"],
                condition=Q(is_current=True),
                name="crm_proj_one_current",
            ),
        ]
        indexes = [
            models.Index(
                fields=["opportunity", "is_current"],
                name="crm_proj_opp_current_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.school_name_snapshot} - "
            f"{self.campaign_name_snapshot} - v{self.version}"
        )


class CommercialProjectionGrade(TimeStampedModel):
    projection = models.ForeignKey(
        CommercialProjection,
        on_delete=models.CASCADE,
        related_name="grades",
        verbose_name="Proyección",
    )
    service = models.ForeignKey(
        SchoolEducationalService,
        on_delete=models.PROTECT,
        related_name="projection_grades",
        verbose_name="Servicio educativo",
    )
    grade = models.ForeignKey(
        Grade,
        on_delete=models.PROTECT,
        related_name="crm_projection_grades",
        verbose_name="Grado",
    )
    level_name_snapshot = models.CharField(
        max_length=100,
        verbose_name="Nivel al proyectar",
    )
    grade_name_snapshot = models.CharField(
        max_length=100,
        verbose_name="Grado al proyectar",
    )
    section_count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name="Número de secciones",
    )
    student_count = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Alumnos proyectados",
    )

    class Meta:
        verbose_name = "Grado de proyección"
        verbose_name_plural = "Grados de proyección"
        ordering = [
            "service__level__name",
            "grade__order",
            "grade__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["projection", "service", "grade"],
                name="crm_proj_grade_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["projection", "service"],
                name="crm_proj_grade_service_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.projection} - "
            f"{self.level_name_snapshot} - "
            f"{self.grade_name_snapshot}"
        )


class CommercialProjectionItem(TimeStampedModel):
    projection = models.ForeignKey(
        CommercialProjection,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Proyección",
    )
    grade_line = models.ForeignKey(
        CommercialProjectionGrade,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Grado proyectado",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="crm_projection_items",
        verbose_name="Producto",
    )
    product_name_snapshot = models.CharField(
        max_length=250,
        verbose_name="Producto al proyectar",
    )
    provider_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="Editorial al proyectar",
    )
    level_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Nivel del producto",
    )
    grade_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Grado del producto",
    )
    area_name_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Área del producto",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Cantidad proyectada",
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio unitario proyectado",
    )
    price_year_snapshot = models.PositiveSmallIntegerField(
        verbose_name="Año del precio",
    )
    price_campaign_snapshot = models.CharField(
        max_length=100,
        verbose_name="Campaña del precio",
    )

    class Meta:
        verbose_name = "Ítem de proyección"
        verbose_name_plural = "Ítems de proyección"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["projection", "grade_line", "product"],
                name="crm_proj_item_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["projection", "product"],
                name="crm_proj_item_product_idx",
            ),
        ]

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return (
            f"{self.projection} - "
            f"{self.product_name_snapshot}"
        )
