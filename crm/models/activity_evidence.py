from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel

from .activity import CommercialActivity


def activity_evidence_upload_to(instance, filename):
    extension = Path(filename or "").suffix.lower()
    safe_extension = extension if extension else ".bin"

    return (
        "crm/activity-evidence/"
        f"{instance.activity.school_id}/"
        f"{instance.activity_id}/"
        f"{uuid4().hex}{safe_extension}"
    )


class CommercialActivityEvidence(TimeStampedModel):
    class EvidenceType(models.TextChoices):
        PHOTO = "photo", "Foto"
        DOCUMENT = "document", "Documento"

    activity = models.ForeignKey(
        CommercialActivity,
        on_delete=models.CASCADE,
        related_name="evidences",
        verbose_name="Actividad comercial",
    )
    evidence_type = models.CharField(
        max_length=20,
        choices=EvidenceType.choices,
        verbose_name="Tipo de evidencia",
    )
    file = models.FileField(
        upload_to=activity_evidence_upload_to,
        max_length=500,
        verbose_name="Archivo",
    )
    original_name = models.CharField(
        max_length=255,
        verbose_name="Nombre original",
    )
    mime_type = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Tipo MIME",
    )
    size_bytes = models.PositiveBigIntegerField(
        default=0,
        verbose_name="Tamaño en bytes",
    )
    note = models.CharField(
        max_length=240,
        blank=True,
        verbose_name="Nota",
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name="Latitud",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name="Longitud",
    )
    accuracy_m = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precisión en metros",
    )
    captured_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de captura",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_crm_activity_evidences",
        verbose_name="Subido por",
    )

    class Meta:
        verbose_name = "Evidencia de actividad comercial"
        verbose_name_plural = "Evidencias de actividades comerciales"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["activity", "created_at"],
                name="crm_evid_activity_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_evidence_type_display()} - {self.original_name}"
