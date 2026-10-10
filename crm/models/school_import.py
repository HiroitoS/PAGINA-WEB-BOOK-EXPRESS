from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class SchoolImportBatch(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        VALIDATED = "validated", "Validado"
        IMPORTED = "imported", "Importado"
        PARTIAL = "partial", "Importado con pendientes"
        ERROR = "error", "Revisión pendiente"

    file = models.FileField(
        upload_to="crm/importaciones/colegios/",
        verbose_name="Archivo Excel",
    )
    population_year = models.PositiveIntegerField(
        verbose_name="Año de población",
    )
    sheet_name = models.CharField(
        max_length=120,
        default="Instituciones",
        verbose_name="Hoja",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Estado",
    )
    total_rows = models.PositiveIntegerField(default=0)
    total_schools = models.PositiveIntegerField(default=0)
    total_new = models.PositiveIntegerField(default=0)
    total_updated = models.PositiveIntegerField(default=0)
    total_warnings = models.PositiveIntegerField(default=0)
    total_errors = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_school_imports",
        verbose_name="Registrado por",
    )

    class Meta:
        verbose_name = "Importación de colegios"
        verbose_name_plural = "Importaciones de colegios"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Importación de colegios #{self.pk} "
            f"({self.population_year})"
        )


class SchoolImportRow(TimeStampedModel):
    class Action(models.TextChoices):
        NEW = "new", "Nuevo"
        UPDATE = "update", "Actualizar"
        ERROR = "error", "Error"

    batch = models.ForeignKey(
        SchoolImportBatch,
        on_delete=models.CASCADE,
        related_name="rows",
        verbose_name="Importación",
    )
    row_number = models.PositiveIntegerField(
        verbose_name="Fila del Excel",
    )
    institution_code = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Código de institución",
    )
    modular_code = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Código modular",
    )
    school_name = models.CharField(
        max_length=220,
        blank=True,
        verbose_name="Nombre del colegio",
    )
    level_name = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Nivel / modalidad",
    )
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        verbose_name="Acción",
    )
    warnings = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Advertencias",
    )
    errors = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Errores que requieren revisión",
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Datos de la fila",
    )
    processed = models.BooleanField(
        default=False,
        verbose_name="Procesado",
    )

    class Meta:
        verbose_name = "Fila de importación de colegios"
        verbose_name_plural = "Filas de importación de colegios"
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_number"],
                name="crm_school_import_unique_row",
            ),
        ]

    def __str__(self):
        return (
            f"Importación #{self.batch_id} - "
            f"fila {self.row_number}"
        )
