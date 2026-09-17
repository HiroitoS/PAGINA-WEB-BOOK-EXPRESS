from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel

from .opportunity import Opportunity
from .school import SchoolContact


class CommercialActivity(TimeStampedModel):
    class ActivityType(models.TextChoices):
        CALL = "call", "Llamada"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Correo"
        MEETING = "meeting", "Reunión"
        VISIT = "visit", "Visita"
        PRESENTATION = "presentation", "Presentación"
        SAMPLE_DELIVERY = "sample_delivery", "Entrega de muestra"
        SAMPLE_RETURN = "sample_return", "Devolución de muestra"
        FOLLOW_UP = "follow_up", "Seguimiento"
        OTHER = "other", "Otro"

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="commercial_activities",
        verbose_name="Oportunidad",
    )
    contact = models.ForeignKey(
        SchoolContact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commercial_activities",
        verbose_name="Contacto del colegio",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_crm_activities",
        verbose_name="Realizado por",
    )
    activity_type = models.CharField(
        max_length=30,
        choices=ActivityType.choices,
        verbose_name="Tipo de actividad",
    )
    summary = models.CharField(
        max_length=200,
        verbose_name="Resumen",
    )
    result = models.TextField(
        verbose_name="Resultado / detalle",
    )
    occurred_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha de la actividad",
    )
    is_important = models.BooleanField(
        default=False,
        verbose_name="Importante",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_activities",
        verbose_name="Registrado por",
    )

    class Meta:
        verbose_name = "Actividad comercial"
        verbose_name_plural = "Actividades comerciales"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(
                fields=["opportunity", "-occurred_at"],
                name="crm_act_opp_date_idx",
            ),
            models.Index(
                fields=["performed_by", "-occurred_at"],
                name="crm_act_user_date_idx",
            ),
            models.Index(
                fields=["activity_type", "-occurred_at"],
                name="crm_act_type_date_idx",
            ),
        ]

    def clean(self):
        if (
            self.opportunity_id
            and self.contact_id
            and self.contact.school_id != self.opportunity.school_id
        ):
            raise ValidationError(
                {
                    "contact": (
                        "El contacto seleccionado no pertenece al colegio "
                        "de la oportunidad."
                    )
                }
            )

    def __str__(self):
        return f"{self.get_activity_type_display()} - {self.opportunity}"
