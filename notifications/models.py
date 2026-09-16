from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class Notification(TimeStampedModel):
    SEVERITY_CHOICES = [
        ("info", "Información"),
        ("success", "Éxito"),
        ("warning", "Advertencia"),
        ("error", "Error"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinatario",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notifications",
        verbose_name="Generada por",
    )
    title = models.CharField(
        max_length=180,
        verbose_name="Título",
    )
    message = models.TextField(
        blank=True,
        verbose_name="Mensaje",
    )
    event_type = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="Tipo de evento",
    )
    module = models.CharField(
        max_length=60,
        db_index=True,
        verbose_name="Módulo",
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default="info",
        db_index=True,
        verbose_name="Severidad",
    )
    link = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="Enlace interno",
    )
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Leída",
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de lectura",
    )
    is_resolved = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Resuelta",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de resolución",
    )

    # Referencia desacoplada para ToDo, Solicitudes, CRM y ERP.
    source_app = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Aplicación origen",
    )
    source_model = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Modelo origen",
    )
    source_id = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Identificador origen",
    )

    # Información complementaria no crítica para renderizado o trazabilidad.
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Metadatos",
    )

    # Permite evitar duplicados en eventos programados o reintentados.
    dedup_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Clave de deduplicación",
    )

    class Meta:
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="notif_rec_read_created_idx",
            ),
            models.Index(
                fields=["recipient", "module", "-created_at"],
                name="notif_rec_module_created_idx",
            ),
            models.Index(
                fields=["recipient", "is_resolved", "-created_at"],
                name="notif_rec_resolved_created_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedup_key"],
                name="unique_notification_dedup_per_recipient",
            ),
        ]

    def __str__(self):
        return f"{self.recipient} - {self.title}"

    def mark_read(self):
        if self.is_read:
            return

        self.is_read = True
        self.read_at = timezone.now()
        self.save(
            update_fields=[
                "is_read",
                "read_at",
                "updated_at",
            ]
        )

    def mark_resolved(self):
        if self.is_resolved:
            return

        self.is_resolved = True
        self.resolved_at = timezone.now()
        self.save(
            update_fields=[
                "is_resolved",
                "resolved_at",
                "updated_at",
            ]
        )
