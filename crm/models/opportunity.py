from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimeStampedModel

from .campaign import Campaign
from .pipeline import Pipeline, PipelineStage
from .school import School, SchoolContact
from .team import CommercialTeam


class Opportunity(TimeStampedModel):
    title = models.CharField(
        max_length=200,
        verbose_name="Oportunidad",
    )
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name="Colegio",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name="Campaña",
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name="Pipeline",
    )
    stage = models.ForeignKey(
        PipelineStage,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name="Etapa actual",
    )
    primary_contact = models.ForeignKey(
        SchoolContact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_opportunities",
        verbose_name="Contacto principal",
    )
    team = models.ForeignKey(
        CommercialTeam,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opportunities",
        verbose_name="Equipo comercial",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_owned_opportunities",
        verbose_name="Asesor responsable",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Resumen / observaciones",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de cierre",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_crm_opportunities",
        verbose_name="Cerrado por",
    )
    closure_note = models.TextField(
        blank=True,
        verbose_name="Motivo / detalle de cierre",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_opportunities",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Oportunidad comercial"
        verbose_name_plural = "Oportunidades comerciales"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["campaign", "stage"],
                name="crm_opp_cmp_stage_idx",
            ),
            models.Index(
                fields=["owner", "stage"],
                name="crm_opp_owner_stage_idx",
            ),
            models.Index(
                fields=["team", "stage"],
                name="crm_opp_team_stage_idx",
            ),
            models.Index(
                fields=["school", "campaign"],
                name="crm_opp_school_cmp_idx",
            ),
            models.Index(
                fields=["closed_at"],
                name="crm_opp_closed_idx",
            ),
        ]

    @property
    def is_closed(self):
        return self.stage.category in {
            PipelineStage.Category.WON,
            PipelineStage.Category.LOST,
        }

    def clean(self):
        errors = {}

        if (
            self.pipeline_id
            and self.stage_id
            and self.stage.pipeline_id != self.pipeline_id
        ):
            errors["stage"] = (
                "La etapa seleccionada no pertenece al pipeline "
                "de la oportunidad."
            )

        if (
            self.school_id
            and self.primary_contact_id
            and self.primary_contact.school_id != self.school_id
        ):
            errors["primary_contact"] = (
                "El contacto seleccionado no pertenece al colegio "
                "de la oportunidad."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.title} - {self.school.name}"


class OpportunityStageHistory(TimeStampedModel):
    class TransitionType(models.TextChoices):
        CREATED = "created", "Creación"
        STAGE_CHANGE = "stage_change", "Cambio de etapa"
        REOPENED = "reopened", "Reapertura"

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="stage_history",
        verbose_name="Oportunidad",
    )
    from_stage = models.ForeignKey(
        PipelineStage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunity_transitions_from",
        verbose_name="Etapa anterior",
    )
    to_stage = models.ForeignKey(
        PipelineStage,
        on_delete=models.PROTECT,
        related_name="opportunity_transitions_to",
        verbose_name="Nueva etapa",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_opportunity_stage_changes",
        verbose_name="Modificado por",
    )
    transition_type = models.CharField(
        max_length=20,
        choices=TransitionType.choices,
        default=TransitionType.STAGE_CHANGE,
        verbose_name="Tipo de transición",
    )
    note = models.TextField(
        blank=True,
        verbose_name="Motivo / observación",
    )

    class Meta:
        verbose_name = "Historial de etapa"
        verbose_name_plural = "Historial de etapas"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["opportunity", "-created_at"],
                name="crm_opp_hist_date_idx",
            ),
        ]

    def __str__(self):
        previous = self.from_stage.name if self.from_stage else "Inicio"
        return f"{self.opportunity} - {previous} → {self.to_stage.name}"
