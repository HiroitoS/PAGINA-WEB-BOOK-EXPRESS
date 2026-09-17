from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.models import TimeStampedModel


class Campaign(TimeStampedModel):
    class CampaignType(models.TextChoices):
        SCHOOL = "school", "Campaña escolar"
        READING_PLAN = "reading_plan", "Plan lector"
        GENERAL = "general", "General"

    class Status(models.TextChoices):
        PLANNING = "planning", "Planificación"
        ACTIVE = "active", "Activa"
        CLOSED = "closed", "Cerrada"

    code = models.CharField(
        max_length=40,
        unique=True,
        verbose_name="Código",
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
    )
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(2000)],
        verbose_name="Año",
    )
    campaign_type = models.CharField(
        max_length=30,
        choices=CampaignType.choices,
        default=CampaignType.SCHOOL,
        verbose_name="Tipo de campaña",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNING,
        verbose_name="Estado",
    )
    starts_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de inicio",
    )
    ends_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de cierre",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_campaigns",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Campaña comercial"
        verbose_name_plural = "Campañas comerciales"
        ordering = ["-year", "name"]
        permissions = [
            ("view_crm", "Puede consultar el CRM"),
            ("manage_campaigns", "Puede gestionar campañas del CRM"),
            ("manage_commercial_teams", "Puede gestionar equipos comerciales"),
            ("manage_schools", "Puede gestionar colegios y contactos"),
            ("assign_schools", "Puede asignar colegios a asesores"),
            ("manage_own_opportunities", "Puede gestionar sus oportunidades"),
            ("assign_opportunities", "Puede asignar oportunidades"),
            ("supervise_crm", "Puede supervisar el CRM comercial"),
            ("manage_quotations", "Puede gestionar cotizaciones"),
            ("manage_adoptions", "Puede gestionar adopciones"),
            ("export_crm_reports", "Puede exportar reportes del CRM"),
        ]
        indexes = [
            models.Index(
                fields=["year", "status"],
                name="crm_cmp_year_status_idx",
            ),
            models.Index(
                fields=["campaign_type", "status"],
                name="crm_cmp_type_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(starts_on__isnull=True)
                    | models.Q(ends_on__isnull=True)
                    | models.Q(ends_on__gte=models.F("starts_on"))
                ),
                name="crm_cmp_valid_dates",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.year})"
