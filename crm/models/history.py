from django.conf import settings
from django.db import models
from django.utils import timezone


class CRMHistoryEvent(models.Model):
    class Category(models.TextChoices):
        SCHOOL = "school", "Colegio"
        CONTACT = "contact", "Contacto"
        ACTIVITY = "activity", "Actividad"
        OPPORTUNITY = "opportunity", "Oportunidad"
        PROJECTION = "projection", "Proyección"
        QUOTATION = "quotation", "Cotización"
        ADOPTION = "adoption", "Adopción"
        POPULATION = "population", "Población"
        ASSIGNMENT = "assignment", "Asignación"
        EVIDENCE = "evidence", "Evidencia"
        OTHER = "other", "Otro"

    school = models.ForeignKey(
        "crm.School",
        on_delete=models.PROTECT,
        related_name="history_events",
        verbose_name="Colegio",
    )
    opportunity = models.ForeignKey(
        "crm.Opportunity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_events",
        verbose_name="Oportunidad",
    )
    contact = models.ForeignKey(
        "crm.SchoolContact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_events",
        verbose_name="Contacto",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_history_events",
        verbose_name="Usuario",
    )
    category = models.CharField(
        max_length=24,
        choices=Category.choices,
        db_index=True,
        verbose_name="Categoría",
    )
    event_type = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Tipo de evento",
    )
    title = models.CharField(
        max_length=220,
        verbose_name="Título",
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )
    source_type = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        verbose_name="Tipo de origen",
    )
    source_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="ID de origen",
    )
    platform = models.CharField(
        max_length=40,
        default="Página Web",
        verbose_name="Plataforma",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Metadatos",
    )
    occurred_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Fecha del evento",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro",
    )

    class Meta:
        verbose_name = "Evento de historial CRM"
        verbose_name_plural = "Eventos de historial CRM"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(
                fields=["school", "-occurred_at"],
                name="crm_hist_school_date_idx",
            ),
            models.Index(
                fields=["opportunity", "-occurred_at"],
                name="crm_hist_opp_date_idx",
            ),
            models.Index(
                fields=["category", "event_type"],
                name="crm_hist_cat_type_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id", "event_type"],
                name="crm_hist_source_event_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.school.name} - {self.title}"
