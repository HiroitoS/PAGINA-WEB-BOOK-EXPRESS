from django.db import models

from core.models import TimeStampedModel


class ContactRequest(TimeStampedModel):
    STATUS_CHOICES = [
    ("new", "Nueva"),
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

    class Meta:
        verbose_name = "Solicitud de contacto"
        verbose_name_plural = "Solicitudes de contacto"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name} - {self.phone}"