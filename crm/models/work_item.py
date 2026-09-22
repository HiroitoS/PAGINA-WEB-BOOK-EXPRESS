from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimeStampedModel

from .activity import CommercialActivity
from .opportunity import Opportunity
from .school import School, SchoolContact


class CRMWorkItemLink(TimeStampedModel):
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="crm_work_item_links",
        verbose_name="Colegio",
    )
    contact = models.ForeignKey(
        SchoolContact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_work_item_links",
        verbose_name="Contacto del colegio",
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_item_links",
        verbose_name="Oportunidad",
    )
    origin_activity = models.ForeignKey(
        CommercialActivity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_work_item_links",
        verbose_name="Actividad de origen",
    )
    task = models.ForeignKey(
        "workspaces.Task",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_links",
        verbose_name="Tarea",
    )
    event = models.ForeignKey(
        "workspaces.CalendarEvent",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_links",
        verbose_name="Evento",
    )
    reminder = models.ForeignKey(
        "workspaces.Reminder",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_links",
        verbose_name="Recordatorio",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_work_item_links",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Vínculo CRM / trabajo"
        verbose_name_plural = "Vínculos CRM / trabajo"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(task__isnull=False)
                        & models.Q(event__isnull=True)
                        & models.Q(reminder__isnull=True)
                    )
                    | (
                        models.Q(task__isnull=True)
                        & models.Q(event__isnull=False)
                        & models.Q(reminder__isnull=True)
                    )
                    | (
                        models.Q(task__isnull=True)
                        & models.Q(event__isnull=True)
                        & models.Q(reminder__isnull=False)
                    )
                ),
                name="crm_work_exactly_one_item",
            ),
            models.UniqueConstraint(
                fields=["task"],
                condition=models.Q(task__isnull=False),
                name="crm_work_unique_task",
            ),
            models.UniqueConstraint(
                fields=["event"],
                condition=models.Q(event__isnull=False),
                name="crm_work_unique_event",
            ),
            models.UniqueConstraint(
                fields=["reminder"],
                condition=models.Q(reminder__isnull=False),
                name="crm_work_unique_reminder",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "-created_at"],
                name="crm_work_school_date_idx",
            ),
            models.Index(
                fields=["opportunity", "-created_at"],
                name="crm_work_opp_date_idx",
            ),
            models.Index(
                fields=["origin_activity", "-created_at"],
                name="crm_work_act_date_idx",
            ),
        ]

    def clean(self):
        errors = {}

        selected_items = sum(
            item is not None
            for item in (self.task_id, self.event_id, self.reminder_id)
        )

        if selected_items != 1:
            raise ValidationError(
                "Debe relacionarse exactamente una tarea, un evento "
                "o un recordatorio."
            )

        if (
            self.school_id
            and self.contact_id
            and self.contact.school_id != self.school_id
        ):
            errors["contact"] = (
                "El contacto seleccionado no pertenece al colegio."
            )

        if (
            self.school_id
            and self.opportunity_id
            and self.opportunity.school_id != self.school_id
        ):
            errors["opportunity"] = (
                "La oportunidad seleccionada no pertenece al colegio."
            )

        if (
            self.school_id
            and self.origin_activity_id
            and self.origin_activity.school_id != self.school_id
        ):
            errors["origin_activity"] = (
                "La actividad de origen no pertenece al colegio."
            )

        if (
            self.origin_activity_id
            and self.opportunity_id
            and self.origin_activity.opportunity_id
            and self.origin_activity.opportunity_id != self.opportunity_id
        ):
            errors["origin_activity"] = (
                "La actividad de origen pertenece a otra oportunidad."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def work_item_type(self):
        if self.task_id:
            return "task"
        if self.event_id:
            return "event"
        return "reminder"

    def __str__(self):
        return f"{self.school} - {self.work_item_type}"
