from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class ContactRequest(TimeStampedModel):
    STATUS_CHOICES = [
        ("new", "Nueva"),
        ("under_review", "En revisión"),
        ("contacted", "Contactado"),
        ("in_follow_up", "En seguimiento"),
        ("closed", "Cerrado"),
        ("discarded", "Descartado"),
    ]

    SOURCE_CHOICES = [
        ("web", "Web"),
        ("whatsapp", "WhatsApp"),
        ("catalog", "Catálogo"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Baja"),
        ("medium", "Media"),
        ("high", "Alta"),
        ("urgent", "Urgente"),
    ]

    full_name = models.CharField(
        max_length=150,
        verbose_name="Nombre completo"
    )
    phone = models.CharField(
        max_length=30,
        verbose_name="Teléfono / WhatsApp"
    )
    email = models.EmailField(
        blank=True,
        verbose_name="Correo electrónico"
    )

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_requests",
        verbose_name="Producto consultado"
    )
    provider = models.ForeignKey(
        "catalog.Provider",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_requests",
        verbose_name="Proveedor / Editorial"
    )

    message = models.TextField(
        verbose_name="Mensaje"
    )
    source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        default="web",
        verbose_name="Origen"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="new",
        verbose_name="Estado"
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="medium",
        verbose_name="Prioridad"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_contact_requests",
        verbose_name="Responsable de atención"
    )
    last_attention_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Última atención"
    )
    next_action_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Próxima acción"
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de cierre"
    )

    class Meta:
        verbose_name = "Solicitud de contacto"
        verbose_name_plural = "Solicitudes de contacto"
        ordering = ["-created_at"]

    def mark_attention(self):
        self.last_attention_at = timezone.now()

    def __str__(self):
        return f"{self.full_name} - {self.phone}"


class ContactRequestComment(TimeStampedModel):
    ACTION_TYPE_CHOICES = [
        ("general", "Comentario general"),
        ("whatsapp", "Contacto por WhatsApp"),
        ("phone", "Llamada telefónica"),
        ("email", "Correo electrónico"),
        ("follow_up", "Seguimiento"),
        ("internal", "Nota interna"),
        ("other", "Otro"),
    ]

    contact_request = models.ForeignKey(
        ContactRequest,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Solicitud"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_request_comments",
        verbose_name="Usuario"
    )
    action_type = models.CharField(
        max_length=30,
        choices=ACTION_TYPE_CHOICES,
        default="general",
        verbose_name="Tipo de acción"
    )
    comment = models.TextField(
        verbose_name="Comentario / evidencia"
    )

    class Meta:
        verbose_name = "Comentario de solicitud"
        verbose_name_plural = "Comentarios de solicitudes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.contact_request} - {self.get_action_type_display()}"


class ContactRequestStatusHistory(models.Model):
    contact_request = models.ForeignKey(
        ContactRequest,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Solicitud"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_request_status_changes",
        verbose_name="Usuario"
    )
    old_status = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Estado anterior"
    )
    new_status = models.CharField(
        max_length=30,
        verbose_name="Estado nuevo"
    )
    note = models.TextField(
        blank=True,
        verbose_name="Nota"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de cambio"
    )

    class Meta:
        verbose_name = "Historial de estado de solicitud"
        verbose_name_plural = "Historial de estados de solicitudes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.old_status} → {self.new_status}"