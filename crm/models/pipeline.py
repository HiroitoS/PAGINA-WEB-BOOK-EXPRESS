from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Pipeline(TimeStampedModel):
    code = models.CharField(
        max_length=60,
        unique=True,
        verbose_name="Código",
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name="Pipeline predeterminado",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_pipelines",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Pipeline comercial"
        verbose_name_plural = "Pipelines comerciales"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="crm_pipeline_one_default",
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_active", "name"],
                name="crm_pipe_active_name_idx",
            ),
        ]

    def __str__(self):
        return self.name


class PipelineStage(TimeStampedModel):
    class Category(models.TextChoices):
        OPEN = "open", "Abierta"
        WON = "won", "Ganada"
        LOST = "lost", "No concretada"

    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name="stages",
        verbose_name="Pipeline",
    )
    code = models.CharField(
        max_length=60,
        verbose_name="Código",
    )
    name = models.CharField(
        max_length=120,
        verbose_name="Nombre",
    )
    order = models.PositiveSmallIntegerField(
        verbose_name="Orden",
    )
    category = models.CharField(
        max_length=10,
        choices=Category.choices,
        default=Category.OPEN,
        verbose_name="Categoría",
    )
    is_initial = models.BooleanField(
        default=False,
        verbose_name="Etapa inicial",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activa",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_pipeline_stages",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Etapa del pipeline"
        verbose_name_plural = "Etapas del pipeline"
        ordering = ["pipeline__name", "order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "code"],
                name="crm_stage_unique_code",
            ),
            models.UniqueConstraint(
                fields=["pipeline", "order"],
                name="crm_stage_unique_order",
            ),
            models.UniqueConstraint(
                fields=["pipeline"],
                condition=models.Q(is_initial=True),
                name="crm_stage_one_initial",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_initial=False)
                    | models.Q(category="open")
                ),
                name="crm_stage_initial_open",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "is_active", "order"],
                name="crm_stage_pipe_active_idx",
            ),
            models.Index(
                fields=["pipeline", "category"],
                name="crm_stage_pipe_cat_idx",
            ),
        ]

    @property
    def is_terminal(self):
        return self.category in {
            self.Category.WON,
            self.Category.LOST,
        }

    def __str__(self):
        return f"{self.pipeline.name} - {self.name}"
